variable "owner_environment" {
  description = "Pinned Web Owner environment with an optional paired User recovery setting."
  type        = map(string)
  default     = null
  nullable    = true

  validation {
    condition = var.owner_environment == null ? true : try(
      contains([6, 8], length(var.owner_environment)) &&
      length(setsubtract(toset(keys(var.owner_environment)), toset([
        "FOLIOVIEW_OWNER_FIREBASE_PROJECT_ID", "FOLIOVIEW_PORTFOLIO_OWNER_ENABLED",
        "FOLIOVIEW_PORTFOLIO_ORIGIN", "FOLIOVIEW_PORTFOLIO_AUDIENCE",
        "FOLIOVIEW_HUB_OWNER_ENABLED", "FOLIOVIEW_HUB_ORIGIN",
        "FOLIOVIEW_USER_OWNER_ENABLED", "FOLIOVIEW_USER_ORIGIN",
      ]))) == 0 &&
      contains(["true", "false"], var.owner_environment.FOLIOVIEW_PORTFOLIO_OWNER_ENABLED) &&
      contains(["true", "false"], var.owner_environment.FOLIOVIEW_HUB_OWNER_ENABLED) &&
      contains(["true", "false"], lookup(var.owner_environment, "FOLIOVIEW_USER_OWNER_ENABLED", "false")) &&
      var.owner_environment.FOLIOVIEW_OWNER_FIREBASE_PROJECT_ID == (
        contains([
          var.owner_environment.FOLIOVIEW_PORTFOLIO_OWNER_ENABLED,
          var.owner_environment.FOLIOVIEW_HUB_OWNER_ENABLED,
          lookup(var.owner_environment, "FOLIOVIEW_USER_OWNER_ENABLED", "false"),
        ], "true") ? var.deployment.project_id : ""
      ) &&
      (var.owner_environment.FOLIOVIEW_PORTFOLIO_OWNER_ENABLED == "true" ? (
        can(regex("^https://portfolio-api-[1-9][0-9]{5,19}\\.${var.deployment.region}\\.run\\.app$", var.owner_environment.FOLIOVIEW_PORTFOLIO_ORIGIN)) &&
        var.owner_environment.FOLIOVIEW_PORTFOLIO_AUDIENCE == var.owner_environment.FOLIOVIEW_PORTFOLIO_ORIGIN
      ) : var.owner_environment.FOLIOVIEW_PORTFOLIO_ORIGIN == "" && var.owner_environment.FOLIOVIEW_PORTFOLIO_AUDIENCE == "") &&
      (var.owner_environment.FOLIOVIEW_HUB_OWNER_ENABLED == "true" ? (
        can(regex("^https://agent-hub-api-[1-9][0-9]{5,19}\\.${var.deployment.region}\\.run\\.app$", var.owner_environment.FOLIOVIEW_HUB_ORIGIN)) &&
        (var.owner_environment.FOLIOVIEW_PORTFOLIO_OWNER_ENABLED != "true" || var.owner_environment.FOLIOVIEW_HUB_ORIGIN == replace(var.owner_environment.FOLIOVIEW_PORTFOLIO_ORIGIN, "https://portfolio-api-", "https://agent-hub-api-"))
      ) : var.owner_environment.FOLIOVIEW_HUB_ORIGIN == "") &&
      (lookup(var.owner_environment, "FOLIOVIEW_USER_OWNER_ENABLED", "false") == "true" ? (
        can(regex("^https://user-api-[1-9][0-9]{5,19}\\.${var.deployment.region}\\.run\\.app$", var.owner_environment.FOLIOVIEW_USER_ORIGIN)) &&
        alltrue([for hint in [
          replace(var.owner_environment.FOLIOVIEW_PORTFOLIO_ORIGIN, "https://portfolio-api-", "https://user-api-"),
          replace(var.owner_environment.FOLIOVIEW_HUB_ORIGIN, "https://agent-hub-api-", "https://user-api-"),
        ] : hint == "" || var.owner_environment.FOLIOVIEW_USER_ORIGIN == hint])
      ) : lookup(var.owner_environment, "FOLIOVIEW_USER_ORIGIN", "") == ""),
      false,
    )
    error_message = "Use the pinned Owner settings with this Firebase project and matching numbered service origins. The User recovery flag and origin must be supplied together."
  }
}
