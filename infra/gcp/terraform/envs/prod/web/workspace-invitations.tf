variable "workspace_invitation_mode" {
  description = "Enable invitation management, optionally with required workspace admission."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.workspace_invitation_mode == null ? true : (
      contains(["management", "required"], var.workspace_invitation_mode) &&
      try(var.owner_environment.FOLIOVIEW_USER_OWNER_ENABLED == "true", false)
    )
    error_message = "Invitation management requires the configured User connection and a reviewed management or required mode."
  }
}
