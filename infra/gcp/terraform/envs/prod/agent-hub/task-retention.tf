variable "task_retention_image" {
  description = "Immutable Agent Hub image containing app.task_retention_worker. Empty omits the job and schedule."
  type        = string
  default     = ""
  nullable    = false
  validation {
    condition = var.task_retention_image == "" || can(regex(
      "^${var.deployment.region}-docker\\.pkg\\.dev/${var.deployment.project_id}/${var.deployment.artifact_repository}/agent-hub-api@sha256:[a-f0-9]{64}$",
      var.task_retention_image,
    ))
    error_message = "Pin the Agent Hub digest in the selected artifact repository."
  }
}

variable "task_retention_schedule_enabled" {
  description = "Unpause scheduled deletion after worker verification and job-specific invocation authorization."
  type        = bool
  default     = false
  nullable    = false
  validation {
    condition     = !var.task_retention_schedule_enabled || var.task_retention_image != ""
    error_message = "Select a task retention image before enabling the schedule."
  }
}

resource "google_cloud_run_v2_job" "task_retention" {
  count               = var.task_retention_image == "" ? 0 : 1
  name                = "agent-hub-task-retention"
  project             = local.project_id
  location            = local.region
  deletion_protection = false
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = "fa-hub-retention-worker@${local.project_id}.iam.gserviceaccount.com"
      max_retries     = 1
      timeout         = "1800s"
      containers {
        image   = var.task_retention_image
        command = ["python", "-m", "app.task_retention_worker"]
        args    = ["--apply"]
        resources {
          limits = { cpu = "1", memory = "512Mi" }
        }
        dynamic "env" {
          for_each = {
            AGENT_HUB_STORE_BACKEND = "firestore"
            FIRESTORE_DATABASE      = "agent-hub"
            FIREBASE_PROJECT_ID     = local.project_id
          }
          content {
            name  = env.key
            value = env.value
          }
        }
      }
    }
  }
}

resource "google_cloud_scheduler_job" "task_retention" {
  count            = var.task_retention_image == "" ? 0 : 1
  name             = "agent-hub-task-retention"
  project          = local.project_id
  region           = local.region
  schedule         = "17 * * * *"
  time_zone        = "Etc/UTC"
  paused           = !var.task_retention_schedule_enabled
  attempt_deadline = "60s"
  retry_config {
    retry_count = 0
  }
  http_target {
    uri         = "https://run.googleapis.com/v2/projects/${local.project_id}/locations/${local.region}/jobs/${google_cloud_run_v2_job.task_retention[0].name}:run"
    http_method = "POST"
    headers     = { "Content-Type" = "application/json" }
    body        = base64encode("{}")
    oauth_token {
      service_account_email = "fa-hub-retention-trigger@${local.project_id}.iam.gserviceaccount.com"
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }
}
