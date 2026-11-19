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

resource "google_firebaserules_ruleset" "market_cache" {
  count   = var.market_cache_database_enabled ? 1 : 0
  project = var.project_id

  source {
    files {
      name    = "firestore.rules"
      content = <<-RULES
        rules_version = '2';
        service cloud.firestore {
          match /databases/{database}/documents {
            match /{document=**} {
              allow read, write: if false;
            }
          }
        }
      RULES
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_firebaserules_release" "market_cache" {
  count        = var.market_cache_database_enabled ? 1 : 0
  project      = var.project_id
  name         = "cloud.firestore/${module.market_cache_database[0].database_id}"
  ruleset_name = google_firebaserules_ruleset.market_cache[0].name

  lifecycle {
    prevent_destroy = true
  }
}
