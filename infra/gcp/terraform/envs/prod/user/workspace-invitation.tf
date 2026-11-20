variable "workspace_invitation" {
  description = "Reviewed Secret Manager version references and authenticated callback identity for User invitations."
  type = object({
    admin_secret_version      = string
    mail_secret_version       = string
    callback_subject          = string
    restrict_workspace_access = optional(bool, false)
  })
  default  = null
  nullable = true

  validation {
    condition = var.workspace_invitation == null || try(
      can(regex("^[1-9][0-9]*$", var.workspace_invitation.admin_secret_version)) &&
      can(regex("^[1-9][0-9]*$", var.workspace_invitation.mail_secret_version)) &&
      can(regex("^[1-9][0-9]{5,30}$", var.workspace_invitation.callback_subject)) &&
      var.hub_trust.USER_SERVICE_AUDIENCE != "" &&
      var.deployment.runtime_account_id != "workspace-admission",
      false,
    )
    error_message = "Use numeric secret versions, a distinct workspace admission caller, and the pinned User audience."
  }
}

locals {
  workspace_invitation_environment = var.workspace_invitation == null ? {} : {
    FOLIOCREW_INVITATIONS_ENABLED         = "1"
    FOLIOCREW_WORKSPACE_ACCESS_RESTRICTED = var.workspace_invitation.restrict_workspace_access ? "1" : "0"
    USER_INVITATION_AUTH_CALLER = jsonencode({
      (var.workspace_invitation.callback_subject) = "workspace-admission@${local.project_id}.iam.gserviceaccount.com"
    })
  }
  workspace_invitation_secrets = var.workspace_invitation == null ? {} : {
    FOLIOCREW_INVITATION_ADMIN_UID = {
      secret  = "projects/${local.project_id}/secrets/foliocrew-invitation-admin-uid"
      version = var.workspace_invitation.admin_secret_version
    }
    FOLIOCREW_INVITATION_MAIL_KEY = {
      secret  = "projects/${local.project_id}/secrets/foliocrew-invitation-mail-key"
      version = var.workspace_invitation.mail_secret_version
    }
  }
}
