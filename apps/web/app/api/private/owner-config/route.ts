import { ownerCapabilities } from "@/lib/server/owner-config";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET() {
  const headers = new Headers({ "Cache-Control": "no-store" });
  if (process.env.FOLIOCREW_WORKSPACE_ACCESS_RESTRICTED === "1") {
    headers.set("X-Foliocrew-Workspace-Invitation", "required");
  }
  if (process.env.FOLIOCREW_INVITATION_UI_ENABLED === "1") {
    headers.set("X-Foliocrew-Invitation-Management", "enabled");
  }
  return Response.json(ownerCapabilities(), { headers });
}
