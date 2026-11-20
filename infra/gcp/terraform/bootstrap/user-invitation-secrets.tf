variable "user_invitation_secrets_enabled" {
  description = "Provision the two empty Secret Manager resources for the User invitation service."
  type        = bool
  default     = false
  nullable    = false
}

locals {
  user_invitation_secret_ids = var.user_invitation_secrets_enabled ? toset([
    "foliocrew-invitation-admin-uid",
    "foliocrew-invitation-mail-key",
  ]) : toset([])
}

resource "google_secret_manager_secret" "user_invitation" {
  for_each  = local.user_invitation_secret_ids
  project   = var.project_id
  secret_id = each.key

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_secret_manager_secret_iam_member" "user_invitation_runtime" {
  for_each  = google_secret_manager_secret.user_invitation
  project   = var.project_id
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.user_deployment.inputs.runtime_account_id}@${var.project_id}.iam.gserviceaccount.com"
}
