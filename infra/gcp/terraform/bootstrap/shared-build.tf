# The existing legacy image publisher is shared by Market, User, Config and Web.
# Manage its build-only grants once; service deployment/runtime grants retain
# their existing per-target owners. No Storage access is required by the current
# exact-Git-source / CLOUD_LOGGING_ONLY image builds.
locals {
  shared_image_build_member = "serviceAccount:fa-build@${var.project_id}.iam.gserviceaccount.com"
  shared_image_build_repositories = toset([
    for target in ["market", "user", "config", "web"] :
    jsondecode(var.deployment_configs[target]).artifactRepository
  ])
}

variable "shared_image_build_legacy_binding" {
  description = "Administrator-only migration: adopt imports the existing exact legacy binding; remove revokes it only after adoption; rollback explicitly restores that same binding. Never an automatic rollback."
  type        = string
  default     = "remove"
  nullable    = false

  validation {
    condition     = contains(["adopt", "remove", "rollback"], var.shared_image_build_legacy_binding)
    error_message = "Use adopt, remove, or explicit rollback for the existing shared image build IAM binding."
  }
}

resource "google_project_iam_member" "shared_image_build_metadata" {
  project = var.project_id
  role    = google_project_iam_custom_role.build_metadata.name
  member  = local.shared_image_build_member
}

resource "google_project_iam_member" "shared_image_build_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = local.shared_image_build_member
}

resource "google_artifact_registry_repository_iam_member" "shared_image_build_images" {
  for_each = local.shared_image_build_repositories

  project    = var.project_id
  location   = var.region
  repository = each.value
  role       = "roles/artifactregistry.writer"
  member     = local.shared_image_build_member
}

# The historical project grant was not managed in this backend. Adoption must
# read that exact existing tuple; do not create a replacement if it is absent.
import {
  for_each = var.shared_image_build_legacy_binding == "adopt" ? { legacy = true } : {}

  to = google_project_iam_member.shared_image_build_legacy[0]
  id = "${var.project_id} roles/cloudbuild.builds.builder ${local.shared_image_build_member}"
}

resource "google_project_iam_member" "shared_image_build_legacy" {
  count = var.shared_image_build_legacy_binding == "remove" ? 0 : 1

  project = var.project_id
  role    = "roles/cloudbuild.builds.builder"
  member  = local.shared_image_build_member

  # Retire only this member/role tuple, after its three replacement grants are
  # prepared. Other members of the project policy are never authoritative here.
  depends_on = [
    google_project_iam_member.shared_image_build_metadata,
    google_project_iam_member.shared_image_build_logging,
    google_artifact_registry_repository_iam_member.shared_image_build_images,
  ]
}
