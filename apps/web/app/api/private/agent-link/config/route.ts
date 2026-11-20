import { agentLinkConfiguration } from "@/lib/server/agent-link";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET(request?: Request) {
  const newest = request && new URL(request.url).search === "?version=2";
  return Response.json(agentLinkConfiguration(process.env, newest ? 2 : 1), {
    headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" },
  });
}
