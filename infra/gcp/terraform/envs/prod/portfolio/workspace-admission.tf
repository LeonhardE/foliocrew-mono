variable "require_workspace_admission" {
  description = "Require the workspace admission claim on directly authenticated user requests."
  type        = bool
  default     = false
  nullable    = false
}
