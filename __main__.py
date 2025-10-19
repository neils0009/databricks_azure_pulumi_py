import pulumi
from pulumi import ResourceOptions, Output, InvokeOptions
from pulumi_azure_native import resources, databricks as azdb
import pulumi_databricks as db

# ---------------------------
# Config (aligns with your TF variables)
# ---------------------------
config = pulumi.Config()
azure_client_id       = config.require("azure_client_id")
azure_client_secret   = config.require_secret("azure_client_secret")
azure_tenant_id       = config.require("azure_tenant_id")
azure_subscription_id = config.require("azure_subscription_id")

# ---------------------------
# Azure: Resource Group
# ---------------------------
rg = resources.ResourceGroup(
    "resourcegroup",
    resource_group_name="databricksPulumiRG",
    location="Australia Southeast",
)

# ---------------------------
# Azure: Managed Resource Group for the Databricks workspace
# Azure requires a separate MRG that the service controls.
# Name it deterministically to avoid collisions.
# ---------------------------
#mrg = resources.ResourceGroup(
#    "managedrg",
#    resource_group_name="databricksRG-mrg",
#    location=rg.location,
#)

# Choose a unique MRG name; don't pre-create it.
mrg_name = "databricksRG-pulumi-azureCRDB-mrg"  # change if you want
mrg_id = f"/subscriptions/{azure_subscription_id}/resourceGroups/{mrg_name}"

# ---------------------------
# Azure: Databricks Workspace (Azure Native)
# REQUIRED: managed_resource_group_id
# ---------------------------
workspace = azdb.Workspace(
    "workspace",
    workspace_name="azureCRDB",
    resource_group_name=rg.name,
    location=rg.location,
    sku={"name": "standard"},
    managed_resource_group_id=mrg_id,
    # You can add optional properties if needed in your org:
    # parameters={
    #     "prepareEncryption": {"value": False},
    #     "enableNoPublicIp": {"value": False},
    # }
    opts=ResourceOptions(depends_on=[rg]),
)

# Expose ARM Resource ID for the provider
workspace_resource_id = workspace.id

# ---------------------------
# Databricks Provider (AAD to Azure DB workspace)
# Mirrors TF provider "databricks" block using AAD creds + workspace ARM id
# ---------------------------
db_provider = db.Provider(
    "db",
    azure_workspace_resource_id=workspace_resource_id,
    azure_client_id=azure_client_id,
    azure_client_secret=azure_client_secret,
    azure_tenant_id=azure_tenant_id,
    # You can also set host/token if you prefer PAT auth instead of AAD:
    # host="https://adb-<workspace-id>.<region>.azuredatabricks.net",
    # token=config.require_secret("databricks_pat"),
    opts=ResourceOptions(depends_on=[workspace]),
)

# Helper for invokes to use this provider
invoke_opts = InvokeOptions(provider=db_provider)

# ---------------------------
# Data sources (equivalents of TF data blocks)
# - Smallest node type that has local disk
# - Latest LTS spark version
# ---------------------------
smallest_node = db.get_node_type_output(local_disk=True, opts=invoke_opts)
latest_lts    = db.get_spark_version_output(long_term_support=True, opts=invoke_opts)

# ---------------------------
# Databricks Instance Pool
# ---------------------------
pool = db.InstancePool(
    "pool",
    instance_pool_name="CodeRedPool",
    min_idle_instances=0,
    max_capacity=10,
    node_type_id=smallest_node.id,
    idle_instance_autotermination_minutes=10,
    opts=pulumi.ResourceOptions(provider=db_provider),
)

# ---------------------------
# Databricks Autoscaling Cluster (uses the pool for driver & workers)
# ---------------------------
cluster = db.Cluster(
    "shared_autoscaling",
    cluster_name="Shared Autoscaling",
    spark_version=latest_lts.id,
    instance_pool_id=pool.id,
    driver_instance_pool_id=pool.id,
    autotermination_minutes=20,
    autoscale=db.ClusterAutoscaleArgs(min_workers=1, max_workers=10),
    spark_conf={"spark.databricks.io.cache.enabled": "true"},
    custom_tags={"createdby": "InfraTeam"},
    opts=pulumi.ResourceOptions(provider=db_provider, depends_on=[workspace]),
)

# ---------------------------
# Exports
# ---------------------------
pulumi.export("resource_group_name", rg.name)
pulumi.export("workspace_id", workspace_resource_id)
pulumi.export("databricks_instance_pool_id", pool.id)
pulumi.export("databricks_cluster_id", cluster.id)
