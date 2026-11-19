variable "private_authority_owner" {
  description = "Exact Owner whose private authority has moved to User."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.private_authority_owner == null ? true : try(
      can(regex("^[a-f0-9]{64}$", var.private_authority_owner)) &&
      var.connector.oauth_enabled &&
      var.agent_owned_mode_enabled &&
      contains(var.agent_owned_allowed_owner_subjects, var.private_authority_owner) &&
      can(regex("^https://agent-hub-api-[1-9][0-9]{5,19}\\.${var.deployment.region}\\.run\\.app$", var.deployment.hub_origin)) &&
      var.sources.user_origin == replace(var.deployment.hub_origin, "https://agent-hub-api-", "https://user-api-") &&
      var.sources.portfolio_origin == replace(var.deployment.hub_origin, "https://agent-hub-api-", "https://portfolio-api-") &&
      length(var.sources.trusted_portfolio_callers) == 1,
      false,
    )
    error_message = "Select one allowed Agent Owner and the exact paired Hub, User, and Portfolio services."
  }
}

locals {
  private_authority_environment = var.private_authority_owner == null ? {} : {
    HUB_USER_PRIVATE_AUTHORITY_OWNER        = var.private_authority_owner
    HUB_USER_VAULT_AUTHORITY_ENABLED        = "1"
    HUB_NATIVE_USER_VAULT_AUTHORITY_ENABLED = "1"
    HUB_REPORT_SOURCE_AUTHORITY_ENABLED     = "1"
    HUB_PORTFOLIO_USER_AUTHORITY_TOKENS     = "1"
  }
}
