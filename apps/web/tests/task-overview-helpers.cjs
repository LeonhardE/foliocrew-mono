const { compile } = require("./resource-library-helpers.cjs");
const types = compile("../lib/task-types.ts");
const request = compile("../lib/task-overview-request.ts", { "./task-types": types });
const inbox = compile("../lib/inbox-types.ts");
const reader = compile("../lib/task-result-reader.ts", { "./inbox-types": inbox });
const providers = compile("../lib/report-provider-attribution.ts");
const detail = compile("../lib/task-detail-read.ts", {
  "./task-types": types,
  "./report-provider-attribution": providers,
  "./workspace-cache": compile("../lib/workspace-cache.ts"),
});
const overview = compile(
  "../lib/task-overview.ts",
  {
    "./task-types": types,
    "./task-overview-request": request,
    "./task-result-reader": reader,
    "./report-provider-attribution": providers,
    "./workspace-cache": compile("../lib/workspace-cache.ts"),
  },
  { setTimeout, clearTimeout },
);
module.exports = { types, request, inbox, reader, providers, overview, detail };
