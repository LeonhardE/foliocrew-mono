resource "google_firebaserules_ruleset" "user_data" {
  count   = var.user_data_database_enabled ? 1 : 0
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

resource "google_firebaserules_release" "user_data" {
  count        = var.user_data_database_enabled ? 1 : 0
  project      = var.project_id
  name         = "cloud.firestore/${module.user_data_database[0].database_id}"
  ruleset_name = google_firebaserules_ruleset.user_data[0].name

  lifecycle {
    prevent_destroy = true
  }
}

module "user_data_runtime_scope" {
  count  = var.user_data_database_enabled ? 1 : 0
  source = "../modules/firestore-access"

  project_id  = var.project_id
  database_id = module.user_data_database[0].database_id
  runtime_service_accounts = {
    runtime = "${local.user_deployment.inputs.runtime_account_id}@${var.project_id}.iam.gserviceaccount.com"
  }

  depends_on = [google_firebaserules_release.user_data]
}
