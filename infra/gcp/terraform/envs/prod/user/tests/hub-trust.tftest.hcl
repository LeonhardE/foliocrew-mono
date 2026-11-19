variables {
  deployment = {
    project_id           = "demo-user-alpha"
    region               = "us-central1"
    artifact_repository  = "alpha-images"
    runtime_account_id   = "alpha-user-runtime"
    creation_image       = "us-central1-docker.pkg.dev/demo-user-alpha/alpha-images/user-api@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    existing_service_uid = "33333333-3333-4333-8333-333333333333"
    web_origin           = "https://web.alpha.example.invalid"
    market_origin        = "https://market.alpha.example.invalid"
  }
}

# Synthetic provider snapshots exercise the production root's adoption guards.
# Plans only: no credentials, provisioner execution, or cloud mutations.
mock_provider "google" {
  override_during = plan

  mock_resource "google_service_account" {
    defaults = {
      id     = "projects/demo-user-alpha/serviceAccounts/alpha-user-runtime@demo-user-alpha.iam.gserviceaccount.com"
      email  = "alpha-user-runtime@demo-user-alpha.iam.gserviceaccount.com"
      member = "serviceAccount:alpha-user-runtime@demo-user-alpha.iam.gserviceaccount.com"
    }
  }
}

# Resolve declarative imports without a provider read or remote state change.
override_resource {
  target          = module.runtime_identity.google_service_account.this
  override_during = plan
  values = {
    id     = "projects/demo-user-alpha/serviceAccounts/alpha-user-runtime@demo-user-alpha.iam.gserviceaccount.com"
    email  = "alpha-user-runtime@demo-user-alpha.iam.gserviceaccount.com"
    member = "serviceAccount:alpha-user-runtime@demo-user-alpha.iam.gserviceaccount.com"
  }
}

override_resource {
  target          = module.user.google_cloud_run_v2_service.service
  override_during = plan
  values = {
    id  = "projects/demo-user-alpha/locations/us-central1/services/user-api"
    uid = "33333333-3333-4333-8333-333333333333"
    uri = "https://user.example.invalid"
  }
}

override_data {
  target = data.google_cloud_run_v2_service.user_boundary
  values = {
    uid                  = "33333333-3333-4333-8333-333333333333"
    invoker_iam_disabled = true
    scaling              = [{ max_instance_count = 1 }]
  }
}

run "legacy_profile_stays_closed" {
  command = plan
  assert {
    condition     = toset(keys(local.environment)) == toset(["FIREBASE_PROJECT_ID", "CORS_ORIGINS", "FIRESTORE_DATABASE", "USER_STORE_BACKEND", "MARKET_API_BASE_URL"]) && length(local.hub_trust_environment) == 0
    error_message = "Use the closed User environment while Hub trust is absent."
  }
}

run "explicit_disabled_stays_closed" {
  command = plan
  variables { hub_trust = { "USER_SERVICE_AUDIENCE" : "", "USER_DELEGATION_AUDIENCE" : "", "USER_DELEGATION_ISSUER" : "", "USER_TRUSTED_HUB_CALLERS" : "" } }
  assert {
    condition     = toset(keys(local.environment)) == toset(["FIREBASE_PROJECT_ID", "CORS_ORIGINS", "FIRESTORE_DATABASE", "USER_STORE_BACKEND", "MARKET_API_BASE_URL"]) && length(local.hub_trust_environment) == 0
    error_message = "User trust settings and adoption boundaries must match the explicit reviewed contract."
  }
}

run "exact_pinned_hub_trust" {
  command = plan
  variables { hub_trust = { "USER_SERVICE_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app", "USER_DELEGATION_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app/internal/v2", "USER_DELEGATION_ISSUER" : "https://agent-hub-api-111222333444.us-central1.run.app", "USER_TRUSTED_HUB_CALLERS" : "{\"123456789012345678901\":\"alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com\"}" } }
  assert {
    condition     = local.hub_trust_environment == var.hub_trust && local.environment.USER_SERVICE_AUDIENCE == var.hub_trust.USER_SERVICE_AUDIENCE && local.environment.FIRESTORE_DATABASE == "user-data" && output.adoption_boundary.invoker_iam_disabled && output.adoption_boundary.service_max_instances == 1
    error_message = "User trust settings and adoption boundaries must match the explicit reviewed contract."
  }
}

run "report_audience_binds_exact_operation_and_does_not_enable_it" {
  command = plan
  variables {
    hub_trust = {
      USER_SERVICE_AUDIENCE    = "https://user-api-111222333444.us-central1.run.app"
      USER_DELEGATION_AUDIENCE = "https://user-api-111222333444.us-central1.run.app/internal/v2"
      USER_DELEGATION_ISSUER   = "https://agent-hub-api-111222333444.us-central1.run.app"
      USER_TRUSTED_HUB_CALLERS = jsonencode({
        "123456789012345678901" = "alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com"
      })
    }
  }
  assert {
    condition = (
      local.environment.USER_REPORT_DELEGATION_AUDIENCE == "${var.hub_trust.USER_SERVICE_AUDIENCE}/internal/v2/private-resources/report-source-decisions" &&
      local.environment.USER_DELEGATION_AUDIENCE == var.hub_trust.USER_DELEGATION_AUDIENCE &&
      !contains(keys(local.environment), "USER_REPORT_SOURCE_DECISIONS")
    )
    error_message = "The report recipient must bind the exact operation and leave activation off."
  }
}

run "reject_wrong_service_audience" {
  command = plan
  variables { hub_trust = { "USER_SERVICE_AUDIENCE" : "https://portfolio-api-111222333444.us-central1.run.app", "USER_DELEGATION_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app/internal/v2", "USER_DELEGATION_ISSUER" : "https://agent-hub-api-111222333444.us-central1.run.app", "USER_TRUSTED_HUB_CALLERS" : "{\"123456789012345678901\":\"alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com\"}" } }
  expect_failures = [var.hub_trust]
}

run "reject_wrong_region" {
  command = plan
  variables { hub_trust = { "USER_SERVICE_AUDIENCE" : "https://user-api-111222333444.europe-west1.run.app", "USER_DELEGATION_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app/internal/v2", "USER_DELEGATION_ISSUER" : "https://agent-hub-api-111222333444.us-central1.run.app", "USER_TRUSTED_HUB_CALLERS" : "{\"123456789012345678901\":\"alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com\"}" } }
  expect_failures = [var.hub_trust]
}

run "reject_wrong_delegation_audience" {
  command = plan
  variables { hub_trust = { "USER_SERVICE_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app", "USER_DELEGATION_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app", "USER_DELEGATION_ISSUER" : "https://agent-hub-api-111222333444.us-central1.run.app", "USER_TRUSTED_HUB_CALLERS" : "{\"123456789012345678901\":\"alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com\"}" } }
  expect_failures = [var.hub_trust]
}

run "reject_wrong_issuer" {
  command = plan
  variables { hub_trust = { "USER_SERVICE_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app", "USER_DELEGATION_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app/internal/v2", "USER_DELEGATION_ISSUER" : "https://untrusted.example.invalid", "USER_TRUSTED_HUB_CALLERS" : "{\"123456789012345678901\":\"alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com\"}" } }
  expect_failures = [var.hub_trust]
}

run "reject_wrong_issuer_project" {
  command = plan
  variables { hub_trust = { "USER_SERVICE_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app", "USER_DELEGATION_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app/internal/v2", "USER_DELEGATION_ISSUER" : "https://agent-hub-api-999888777666.us-central1.run.app", "USER_TRUSTED_HUB_CALLERS" : "{\"123456789012345678901\":\"alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com\"}" } }
  expect_failures = [var.hub_trust]
}

run "reject_foreign_runtime" {
  command = plan
  variables { hub_trust = { "USER_SERVICE_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app", "USER_DELEGATION_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app/internal/v2", "USER_DELEGATION_ISSUER" : "https://agent-hub-api-111222333444.us-central1.run.app", "USER_TRUSTED_HUB_CALLERS" : "{\"123456789012345678901\":\"hub-runtime@foreign-project.iam.gserviceaccount.com\"}" } }
  expect_failures = [var.hub_trust]
}

run "reject_self_runtime" {
  command = plan
  variables { hub_trust = { "USER_SERVICE_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app", "USER_DELEGATION_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app/internal/v2", "USER_DELEGATION_ISSUER" : "https://agent-hub-api-111222333444.us-central1.run.app", "USER_TRUSTED_HUB_CALLERS" : "{\"123456789012345678901\":\"alpha-user-runtime@demo-user-alpha.iam.gserviceaccount.com\"}" } }
  expect_failures = [var.hub_trust]
}

run "reject_noncanonical_callers" {
  command = plan
  variables { hub_trust = { "USER_SERVICE_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app", "USER_DELEGATION_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app/internal/v2", "USER_DELEGATION_ISSUER" : "https://agent-hub-api-111222333444.us-central1.run.app", "USER_TRUSTED_HUB_CALLERS" : " {\"123456789012345678901\":\"alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com\"}" } }
  expect_failures = [var.hub_trust]
}

run "reject_non_numeric_subject" {
  command = plan
  variables { hub_trust = { "USER_SERVICE_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app", "USER_DELEGATION_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app/internal/v2", "USER_DELEGATION_ISSUER" : "https://agent-hub-api-111222333444.us-central1.run.app", "USER_TRUSTED_HUB_CALLERS" : "{\"self-reported\":\"alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com\"}" } }
  expect_failures = [var.hub_trust]
}

run "reject_leading_zero_subject" {
  command = plan
  variables { hub_trust = { "USER_SERVICE_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app", "USER_DELEGATION_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app/internal/v2", "USER_DELEGATION_ISSUER" : "https://agent-hub-api-111222333444.us-central1.run.app", "USER_TRUSTED_HUB_CALLERS" : "{\"0123\":\"alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com\"}" } }
  expect_failures = [var.hub_trust]
}

run "reject_multiple_callers" {
  command = plan
  variables { hub_trust = { "USER_SERVICE_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app", "USER_DELEGATION_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app/internal/v2", "USER_DELEGATION_ISSUER" : "https://agent-hub-api-111222333444.us-central1.run.app", "USER_TRUSTED_HUB_CALLERS" : "{\"123\":\"alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com\",\"456\":\"other-runtime@demo-user-alpha.iam.gserviceaccount.com\"}" } }
  expect_failures = [var.hub_trust]
}

run "reject_malformed_callers" {
  command = plan
  variables { hub_trust = { "USER_SERVICE_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app", "USER_DELEGATION_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app/internal/v2", "USER_DELEGATION_ISSUER" : "https://agent-hub-api-111222333444.us-central1.run.app", "USER_TRUSTED_HUB_CALLERS" : "not-json" } }
  expect_failures = [var.hub_trust]
}

run "reject_partial_disabled" {
  command = plan
  variables { hub_trust = { "USER_SERVICE_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app", "USER_DELEGATION_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app/internal/v2", "USER_DELEGATION_ISSUER" : "", "USER_TRUSTED_HUB_CALLERS" : "{\"123456789012345678901\":\"alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com\"}" } }
  expect_failures = [var.hub_trust]
}

run "reject_extra_environment" {
  command = plan
  variables { hub_trust = { "USER_SERVICE_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app", "USER_DELEGATION_AUDIENCE" : "https://user-api-111222333444.us-central1.run.app/internal/v2", "USER_DELEGATION_ISSUER" : "https://agent-hub-api-111222333444.us-central1.run.app", "USER_TRUSTED_HUB_CALLERS" : "{\"123456789012345678901\":\"alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com\"}", "USER_JWKS_URL" : "https://wrong.invalid" } }
  expect_failures = [var.hub_trust]
}

run "private_recovery_accepts_one_distinct_web_workload_without_enabling_reads" {
  command = plan
  variables {
    hub_trust = {
      USER_SERVICE_AUDIENCE       = ""
      USER_DELEGATION_AUDIENCE    = ""
      USER_DELEGATION_ISSUER      = ""
      USER_TRUSTED_HUB_CALLERS    = ""
      USER_PRIVATE_OWNER_AUDIENCE = "https://user-api-111222333444.us-central1.run.app"
      USER_PRIVATE_OWNER_WEB_CALLER = jsonencode({
        "987654321098765432109" = "alpha-web-runtime@demo-user-alpha.iam.gserviceaccount.com"
      })
    }
  }
  assert {
    condition = (
      local.environment.USER_PRIVATE_OWNER_AUDIENCE == var.hub_trust.USER_PRIVATE_OWNER_AUDIENCE &&
      local.environment.USER_PRIVATE_OWNER_WEB_CALLER == var.hub_trust.USER_PRIVATE_OWNER_WEB_CALLER &&
      !contains(keys(local.environment), "USER_PRIVATE_RECOVERY_READ") &&
      !contains(keys(local.environment), "USER_REPORT_DELEGATION_AUDIENCE")
    )
    error_message = "Consume the Web identity without activating recovery or unrelated Hub trust."
  }
}

run "private_recovery_rejects_the_hub_as_its_web_workload" {
  command = plan
  variables {
    hub_trust = {
      USER_SERVICE_AUDIENCE    = "https://user-api-111222333444.us-central1.run.app"
      USER_DELEGATION_AUDIENCE = "https://user-api-111222333444.us-central1.run.app/internal/v2"
      USER_DELEGATION_ISSUER   = "https://agent-hub-api-111222333444.us-central1.run.app"
      USER_TRUSTED_HUB_CALLERS = jsonencode({
        "123456789012345678901" = "alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com"
      })
      USER_PRIVATE_OWNER_AUDIENCE = "https://user-api-111222333444.us-central1.run.app"
      USER_PRIVATE_OWNER_WEB_CALLER = jsonencode({
        "987654321098765432109" = "alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com"
      })
    }
  }
  expect_failures = [var.hub_trust]
}

run "private_recovery_rejects_a_different_numbered_user_audience" {
  command = plan
  variables {
    hub_trust = {
      USER_SERVICE_AUDIENCE    = "https://user-api-111222333444.us-central1.run.app"
      USER_DELEGATION_AUDIENCE = "https://user-api-111222333444.us-central1.run.app/internal/v2"
      USER_DELEGATION_ISSUER   = "https://agent-hub-api-111222333444.us-central1.run.app"
      USER_TRUSTED_HUB_CALLERS = jsonencode({
        "123456789012345678901" = "alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com"
      })
      USER_PRIVATE_OWNER_AUDIENCE = "https://user-api-555555555555.us-central1.run.app"
      USER_PRIVATE_OWNER_WEB_CALLER = jsonencode({
        "987654321098765432109" = "alpha-web-runtime@demo-user-alpha.iam.gserviceaccount.com"
      })
    }
  }
  expect_failures = [var.hub_trust]
}

override_data {
  target = data.google_service_account.private_rollout_portfolio
  values = {
    email     = "alpha-portfolio-runtime@demo-user-alpha.iam.gserviceaccount.com"
    unique_id = "222333444555666777888"
  }
}

override_data {
  target = data.google_cloud_run_v2_service.private_rollout_portfolio
  values = {
    template = [{ service_account = "alpha-portfolio-runtime@demo-user-alpha.iam.gserviceaccount.com" }]
  }
}

run "selected_owner_preparation" {
  command = plan
  variables {
    hub_trust = {
      USER_SERVICE_AUDIENCE         = "https://user-api-111222333444.us-central1.run.app"
      USER_DELEGATION_AUDIENCE      = "https://user-api-111222333444.us-central1.run.app/internal/v2"
      USER_DELEGATION_ISSUER        = "https://agent-hub-api-111222333444.us-central1.run.app"
      USER_TRUSTED_HUB_CALLERS      = jsonencode({ "111000111000111000111" = "alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com" })
      USER_PRIVATE_OWNER_AUDIENCE   = "https://user-api-111222333444.us-central1.run.app"
      USER_PRIVATE_OWNER_WEB_CALLER = jsonencode({ "999888777666555444333" = "alpha-web-runtime@demo-user-alpha.iam.gserviceaccount.com" })
    }
    private_rollout = {
      phase                = "prepare"
      owner_subject        = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      portfolio_subject    = "222333444555666777888"
      portfolio_account_id = "alpha-portfolio-runtime"
    }
  }

  assert {
    condition = (
      local.environment.USER_PRIVATE_SELECTED_OWNER == var.private_rollout.owner_subject &&
      local.environment.USER_PRIVATE_HANDOVER == "true" &&
      local.environment.USER_PRIVATE_RECOVERY_READ == "true" &&
      length(local.private_current_environment) == 0
    )
    error_message = "Preparation must expose only selected Owner handover and recovery."
  }
}

run "selected_owner_active" {
  command = plan
  variables {
    hub_trust = {
      USER_SERVICE_AUDIENCE         = "https://user-api-111222333444.us-central1.run.app"
      USER_DELEGATION_AUDIENCE      = "https://user-api-111222333444.us-central1.run.app/internal/v2"
      USER_DELEGATION_ISSUER        = "https://agent-hub-api-111222333444.us-central1.run.app"
      USER_TRUSTED_HUB_CALLERS      = jsonencode({ "111000111000111000111" = "alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com" })
      USER_PRIVATE_OWNER_AUDIENCE   = "https://user-api-111222333444.us-central1.run.app"
      USER_PRIVATE_OWNER_WEB_CALLER = jsonencode({ "999888777666555444333" = "alpha-web-runtime@demo-user-alpha.iam.gserviceaccount.com" })
    }
    private_rollout = {
      phase                = "active"
      owner_subject        = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      portfolio_subject    = "222333444555666777888"
      portfolio_account_id = "alpha-portfolio-runtime"
    }
  }

  assert {
    condition = (
      local.environment.USER_PRIVATE_SELECTED_OWNER == var.private_rollout.owner_subject &&
      local.environment.USER_PRIVATE_OWNER_CURRENT == "true" &&
      local.environment.USER_PRIVATE_RESOURCE_DIRECTORY == "true" &&
      local.environment.USER_PRIVATE_SOURCE_INVALIDATIONS == "true" &&
      local.environment.USER_REPORT_SOURCE_DECISIONS == "true" &&
      jsondecode(local.environment.USER_PRIVATE_PORTFOLIO_CALLER)[var.private_rollout.portfolio_subject] == "alpha-portfolio-runtime@demo-user-alpha.iam.gserviceaccount.com"
    )
    error_message = "Current authority must carry the exact Portfolio identity and selected Owner."
  }
}

run "reject_unbounded_owner" {
  command = plan
  variables {
    hub_trust = {
      USER_SERVICE_AUDIENCE         = "https://user-api-111222333444.us-central1.run.app"
      USER_DELEGATION_AUDIENCE      = "https://user-api-111222333444.us-central1.run.app/internal/v2"
      USER_DELEGATION_ISSUER        = "https://agent-hub-api-111222333444.us-central1.run.app"
      USER_TRUSTED_HUB_CALLERS      = jsonencode({ "111000111000111000111" = "alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com" })
      USER_PRIVATE_OWNER_AUDIENCE   = "https://user-api-111222333444.us-central1.run.app"
      USER_PRIVATE_OWNER_WEB_CALLER = jsonencode({ "999888777666555444333" = "alpha-web-runtime@demo-user-alpha.iam.gserviceaccount.com" })
    }
    private_rollout = {
      phase                = "active"
      owner_subject        = "*"
      portfolio_subject    = "222333444555666777888"
      portfolio_account_id = "alpha-portfolio-runtime"
    }
  }

  expect_failures = [var.private_rollout]
}

run "reject_reused_workload_subject" {
  command = plan
  variables {
    hub_trust = {
      USER_SERVICE_AUDIENCE         = "https://user-api-111222333444.us-central1.run.app"
      USER_DELEGATION_AUDIENCE      = "https://user-api-111222333444.us-central1.run.app/internal/v2"
      USER_DELEGATION_ISSUER        = "https://agent-hub-api-111222333444.us-central1.run.app"
      USER_TRUSTED_HUB_CALLERS      = jsonencode({ "111000111000111000111" = "alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com" })
      USER_PRIVATE_OWNER_AUDIENCE   = "https://user-api-111222333444.us-central1.run.app"
      USER_PRIVATE_OWNER_WEB_CALLER = jsonencode({ "999888777666555444333" = "alpha-web-runtime@demo-user-alpha.iam.gserviceaccount.com" })
    }
    private_rollout = {
      phase                = "active"
      owner_subject        = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      portfolio_subject    = "111000111000111000111"
      portfolio_account_id = "alpha-portfolio-runtime"
    }
  }

  expect_failures = [var.private_rollout]
}

run "reject_different_live_workload_subject" {
  command = plan
  variables {
    hub_trust = {
      USER_SERVICE_AUDIENCE         = "https://user-api-111222333444.us-central1.run.app"
      USER_DELEGATION_AUDIENCE      = "https://user-api-111222333444.us-central1.run.app/internal/v2"
      USER_DELEGATION_ISSUER        = "https://agent-hub-api-111222333444.us-central1.run.app"
      USER_TRUSTED_HUB_CALLERS      = jsonencode({ "111000111000111000111" = "alpha-hub-runtime@demo-user-alpha.iam.gserviceaccount.com" })
      USER_PRIVATE_OWNER_AUDIENCE   = "https://user-api-111222333444.us-central1.run.app"
      USER_PRIVATE_OWNER_WEB_CALLER = jsonencode({ "999888777666555444333" = "alpha-web-runtime@demo-user-alpha.iam.gserviceaccount.com" })
    }
    private_rollout = {
      phase                = "active"
      owner_subject        = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      portfolio_subject    = "555888777444333222111"
      portfolio_account_id = "alpha-portfolio-runtime"
    }
  }

  expect_failures = [data.google_service_account.private_rollout_portfolio]
}
