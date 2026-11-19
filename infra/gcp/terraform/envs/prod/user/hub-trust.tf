# The reviewed User deployment projection supplies the Hub trust fields and
# can also pin one Web workload for private recovery.
variable "hub_trust" {
  description = "Pinned User trust map with optional Web workload settings for private recovery."
  type        = map(string)
  default     = null
  nullable    = true

  validation {
    condition = var.hub_trust == null ? true : try(
      contains([4, 6], length(var.hub_trust)) &&
      length(setsubtract(toset(keys(var.hub_trust)), toset([
        "USER_SERVICE_AUDIENCE", "USER_DELEGATION_AUDIENCE",
        "USER_DELEGATION_ISSUER", "USER_TRUSTED_HUB_CALLERS",
        "USER_PRIVATE_OWNER_AUDIENCE", "USER_PRIVATE_OWNER_WEB_CALLER",
        ]))) == 0 && (
        alltrue([for value in [
          var.hub_trust.USER_SERVICE_AUDIENCE, var.hub_trust.USER_DELEGATION_AUDIENCE,
          var.hub_trust.USER_DELEGATION_ISSUER, var.hub_trust.USER_TRUSTED_HUB_CALLERS,
          ] : value == ""]) || (
          can(regex("^https://user-api-[1-9][0-9]{5,19}\\.${var.deployment.region}\\.run\\.app$", var.hub_trust.USER_SERVICE_AUDIENCE)) &&
          var.hub_trust.USER_DELEGATION_AUDIENCE == "${var.hub_trust.USER_SERVICE_AUDIENCE}/internal/v2" &&
          var.hub_trust.USER_DELEGATION_ISSUER == replace(var.hub_trust.USER_SERVICE_AUDIENCE, "https://user-api-", "https://agent-hub-api-") &&
          length(var.hub_trust.USER_TRUSTED_HUB_CALLERS) <= 4096 &&
          length(keys(jsondecode(var.hub_trust.USER_TRUSTED_HUB_CALLERS))) == 1 &&
          jsonencode(jsondecode(var.hub_trust.USER_TRUSTED_HUB_CALLERS)) == var.hub_trust.USER_TRUSTED_HUB_CALLERS &&
          can(regex("^[1-9][0-9]{0,127}$", keys(jsondecode(var.hub_trust.USER_TRUSTED_HUB_CALLERS))[0])) &&
          can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]@${var.deployment.project_id}\\.iam\\.gserviceaccount\\.com$", values(jsondecode(var.hub_trust.USER_TRUSTED_HUB_CALLERS))[0])) &&
          values(jsondecode(var.hub_trust.USER_TRUSTED_HUB_CALLERS))[0] != "${var.deployment.runtime_account_id}@${var.deployment.project_id}.iam.gserviceaccount.com"
        )
        ) && (length(var.hub_trust) == 4 ? true : (
          can(regex("^https://user-api-[1-9][0-9]{5,19}\\.${var.deployment.region}\\.run\\.app$", var.hub_trust.USER_PRIVATE_OWNER_AUDIENCE)) &&
          (var.hub_trust.USER_SERVICE_AUDIENCE == "" || var.hub_trust.USER_PRIVATE_OWNER_AUDIENCE == var.hub_trust.USER_SERVICE_AUDIENCE) &&
          length(var.hub_trust.USER_PRIVATE_OWNER_WEB_CALLER) <= 2048 &&
          length(keys(jsondecode(var.hub_trust.USER_PRIVATE_OWNER_WEB_CALLER))) == 1 &&
          jsonencode(jsondecode(var.hub_trust.USER_PRIVATE_OWNER_WEB_CALLER)) == var.hub_trust.USER_PRIVATE_OWNER_WEB_CALLER &&
          can(regex("^[1-9][0-9]{0,127}$", keys(jsondecode(var.hub_trust.USER_PRIVATE_OWNER_WEB_CALLER))[0])) &&
          can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]@${var.deployment.project_id}\\.iam\\.gserviceaccount\\.com$", values(jsondecode(var.hub_trust.USER_PRIVATE_OWNER_WEB_CALLER))[0])) &&
          values(jsondecode(var.hub_trust.USER_PRIVATE_OWNER_WEB_CALLER))[0] != "${var.deployment.runtime_account_id}@${var.deployment.project_id}.iam.gserviceaccount.com" &&
          length(setintersection(
            keys(jsondecode(var.hub_trust.USER_PRIVATE_OWNER_WEB_CALLER)),
            try(keys(jsondecode(var.hub_trust.USER_TRUSTED_HUB_CALLERS)), []),
          )) == 0 &&
          length(setintersection(
            values(jsondecode(var.hub_trust.USER_PRIVATE_OWNER_WEB_CALLER)),
            try(values(jsondecode(var.hub_trust.USER_TRUSTED_HUB_CALLERS)), []),
          )) == 0
      )),
      false,
    )
    error_message = "Use the reviewed Hub trust map and, when present, a paired exact User audience and one distinct same-project Web identity."
  }
}
