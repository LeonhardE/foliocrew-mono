variable "user_data_database_enabled" {
  description = "Provision the protected User database before the scoped INF-023 data copy."
  type        = bool
  default     = false
  nullable    = false
}

module "user_data_database" {
  count  = var.user_data_database_enabled ? 1 : 0
  source = "../modules/firestore-database"

  project_id  = var.project_id
  database_id = "user-data"
  location_id = var.region
}
