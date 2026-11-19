variable "market_cache_database_enabled" {
  description = "Provision the protected Market cache database in administrator state for the INF-022 copy stage."
  type        = bool
  default     = false
  nullable    = false
}

module "market_cache_database" {
  count  = var.market_cache_database_enabled ? 1 : 0
  source = "../modules/firestore-database"

  project_id  = var.project_id
  database_id = "market-cache"
  location_id = var.region
}
