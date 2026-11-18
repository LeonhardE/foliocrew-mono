variable "workspace_edge" {
  description = "Optional exact HTTPS browser origin and raw Ed25519 public key for the managed Workbench edge."
  type = object({
    browser_origin = string
    public_key     = string
  })
  default  = null
  nullable = true

  validation {
    condition = var.workspace_edge == null ? true : (
      length(var.workspace_edge.browser_origin) <= 261 &&
      can(regex("^https://([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]([a-z0-9-]{0,61}[a-z0-9])?$", var.workspace_edge.browser_origin)) &&
      can(regex("^[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$", var.workspace_edge.public_key))
    )
    error_message = "Provide the exact HTTPS DNS origin and a canonical unpadded base64url Ed25519 public key, or leave the edge disabled."
  }
}
