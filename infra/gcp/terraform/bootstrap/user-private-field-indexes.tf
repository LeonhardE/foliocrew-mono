resource "google_firestore_field" "user_private_opaque" {
  for_each = var.user_data_database_enabled ? {
    archive_record = { collection = "user_private_archive_records", field = "record" }
    recovery_view  = { collection = "user_private_recovery_heads", field = "view" }
    registry_entry = { collection = "user_private_registry_history", field = "entry" }
    vault_baseline = { collection = "user_private_vault_baselines", field = "body" }
  } : {}

  project    = var.project_id
  database   = module.user_data_database[0].database_id
  collection = each.value.collection
  field      = each.value.field

  # Recovery reads these opaque payloads by document ID only.
  index_config {}
}
