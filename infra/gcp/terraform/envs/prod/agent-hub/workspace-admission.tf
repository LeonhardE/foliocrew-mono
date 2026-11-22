variable "require_workspace_admission" {
  description = "Require the workspace admission claim on directly authenticated user requests."
  type        = bool
  default     = false
  nullable    = false
}

variable "agent_owned_admitted_users_enabled" {
  description = "Allow verified workspace invitees to enroll in personal Agent mode."
  type        = bool
  default     = false
  nullable    = false

  validation {
    condition = !var.agent_owned_admitted_users_enabled || (
      var.require_workspace_admission && var.agent_owned_mode_enabled
    )
    error_message = "Agent access for invitees requires both verified workspace admission and personal Agent mode."
  }
}
