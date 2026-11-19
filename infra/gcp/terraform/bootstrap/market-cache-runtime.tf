module "market_cache_runtime_scope" {
  count  = var.market_cache_database_enabled ? 1 : 0
  source = "../modules/firestore-access"

  project_id  = var.project_id
  database_id = module.market_cache_database[0].database_id
  runtime_service_accounts = {
    runtime = "${local.market_deployment.inputs.runtime_account_id}@${var.project_id}.iam.gserviceaccount.com"
  }

  depends_on = [google_firebaserules_release.market_cache]
}
