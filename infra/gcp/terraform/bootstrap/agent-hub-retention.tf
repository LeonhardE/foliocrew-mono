# Optional Agent Hub retention identities and their narrowly scoped grants.
variable "agent_hub_retention_stage" {
  type        = string
  description = "Use prepare to create worker/trigger identities, then invoker only after the named retention job exists."
  default     = "none"
  nullable    = false
  validation {
    condition = contains(["none", "prepare", "invoker"], var.agent_hub_retention_stage) && (
      var.agent_hub_retention_stage == "none" || var.agent_hub_provisioning_stage == "service"
    )
    error_message = "Retention requires the existing Hub service. Use none, prepare, or invoker."
  }
}

resource "google_project_service" "agent_hub_scheduler" {
  count              = var.agent_hub_retention_stage == "none" ? 0 : 1
  project            = var.project_id
  service            = "cloudscheduler.googleapis.com"
  disable_on_destroy = false
}

module "agent_hub_retention_identity" {
  for_each = var.agent_hub_retention_stage == "none" ? {} : {
    "worker"  = "fa-hub-retention-worker"
    "trigger" = "fa-hub-retention-trigger"
  }
  source       = "../modules/service-identity"
  project_id   = var.project_id
  account_id   = each.value
  display_name = "Foliocrew Hub retention ${each.key}"
  description  = "Dedicated identity for Agent Hub task retention."
}

module "agent_hub_retention_database" {
  count       = var.agent_hub_retention_stage == "none" ? 0 : 1
  source      = "../modules/firestore-access"
  project_id  = var.project_id
  database_id = "agent-hub"
  runtime_service_accounts = {
    worker = "fa-hub-retention-worker@${var.project_id}.iam.gserviceaccount.com"
  }
  depends_on = [module.agent_hub_retention_identity]
}

resource "google_cloud_run_v2_job_iam_member" "agent_hub_retention_trigger" {
  count      = var.agent_hub_retention_stage == "invoker" ? 1 : 0
  project    = var.project_id
  location   = var.region
  name       = "agent-hub-task-retention"
  role       = "roles/run.invoker"
  member     = "serviceAccount:fa-hub-retention-trigger@${var.project_id}.iam.gserviceaccount.com"
  depends_on = [module.agent_hub_retention_identity]
}
