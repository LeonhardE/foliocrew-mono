variable "private_rollout" {
  description = "One selected User private authority stage with the exact Portfolio workload."
  type = object({
    phase                = string
    owner_subject        = string
    portfolio_subject    = string
    portfolio_account_id = string
  })
  default  = null
  nullable = true

  validation {
    condition = var.private_rollout == null ? true : try(
      contains(["prepare", "active"], var.private_rollout.phase) &&
      can(regex("^[a-f0-9]{64}$", var.private_rollout.owner_subject)) &&
      can(regex("^[1-9][0-9]{0,127}$", var.private_rollout.portfolio_subject)) &&
      can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.private_rollout.portfolio_account_id)) &&
      var.private_rollout.portfolio_account_id != var.deployment.runtime_account_id &&
      var.hub_trust.USER_SERVICE_AUDIENCE != "" &&
      length(keys(jsondecode(var.hub_trust.USER_TRUSTED_HUB_CALLERS))) == 1 &&
      length(keys(jsondecode(var.hub_trust.USER_PRIVATE_OWNER_WEB_CALLER))) == 1 &&
      alltrue([
        for callers in [
          jsondecode(var.hub_trust.USER_TRUSTED_HUB_CALLERS),
          jsondecode(var.hub_trust.USER_PRIVATE_OWNER_WEB_CALLER),
          ] : (
          !contains(keys(callers), var.private_rollout.portfolio_subject) &&
          !contains(values(callers), "${var.private_rollout.portfolio_account_id}@${var.deployment.project_id}.iam.gserviceaccount.com")
        )
      ]),
      false,
    )
    error_message = "Select one Owner, a supported rollout phase, and one Portfolio identity distinct from User, Web and Hub."
  }
}

locals {
  portfolio_workload_email = var.private_rollout == null ? null : "${var.private_rollout.portfolio_account_id}@${local.project_id}.iam.gserviceaccount.com"
  private_prepare_environment = var.private_rollout == null ? {} : {
    USER_PRIVATE_SELECTED_OWNER = var.private_rollout.owner_subject
    USER_PRIVATE_HANDOVER       = "true"
    USER_PRIVATE_RECOVERY_READ  = "true"
  }
  private_current_environment = try(var.private_rollout.phase, null) != "active" ? {} : {
    USER_PRIVATE_OWNER_CURRENT        = "true"
    USER_PRIVATE_AUTHORITY_READS      = "true"
    USER_PRIVATE_SOURCE_REGISTRATIONS = "true"
    USER_PRIVATE_SOURCE_INVALIDATIONS = "true"
    USER_PRIVATE_REGISTRY_UPDATES     = "true"
    USER_PRIVATE_RESOURCE_DIRECTORY   = "true"
    USER_REPORT_SOURCE_DECISIONS      = "true"
    USER_PRIVATE_PORTFOLIO_CALLER = jsonencode({
      (var.private_rollout.portfolio_subject) = local.portfolio_workload_email
    })
  }
}

data "google_service_account" "private_rollout_portfolio" {
  count      = var.private_rollout == null ? 0 : 1
  project    = local.project_id
  account_id = var.private_rollout.portfolio_account_id

  lifecycle {
    postcondition {
      condition     = self.unique_id == var.private_rollout.portfolio_subject && self.email == local.portfolio_workload_email
      error_message = "The referenced Portfolio workload account was replaced or its subject differs from the reviewed input."
    }
  }
}

data "google_cloud_run_v2_service" "private_rollout_portfolio" {
  count    = var.private_rollout == null ? 0 : 1
  project  = local.project_id
  location = local.region
  name     = "portfolio-api"

  lifecycle {
    postcondition {
      condition     = self.template[0].service_account == data.google_service_account.private_rollout_portfolio[0].email
      error_message = "The live Portfolio service must use the exact reviewed workload account."
    }
  }
}
