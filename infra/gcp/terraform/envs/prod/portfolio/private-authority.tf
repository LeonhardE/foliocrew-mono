variable "private_authority_owner" {
  description = "Exact Owner whose current authority and source fences are served by User."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.private_authority_owner == null ? true : try(
      can(regex("^[a-f0-9]{64}$", var.private_authority_owner)) &&
      var.hub_trust.PORTFOLIO_SERVICE_AUDIENCE != "" &&
      length(keys(jsondecode(var.hub_trust.PORTFOLIO_TRUSTED_HUB_CALLERS))) == 1,
      false,
    )
    error_message = "Select one Owner and the existing exact Portfolio and Hub trust configuration."
  }
}

locals {
  private_authority_environment = var.private_authority_owner == null ? {} : {
    PORTFOLIO_USER_AUTHORITY_OWNER  = var.private_authority_owner
    PORTFOLIO_USER_AUTHORITY_ORIGIN = replace(var.hub_trust.PORTFOLIO_SERVICE_AUDIENCE, "https://portfolio-api-", "https://user-api-")
  }
}
