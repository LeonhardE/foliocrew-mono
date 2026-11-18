import { cp, mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const output = process.argv[2];
const workspaceAddress = process.env.FOLIOCREW_WORKSPACE_URL;

if (!output || !workspaceAddress || process.argv.length !== 3) {
  throw new Error("Set FOLIOCREW_WORKSPACE_URL and supply a new landing output directory.");
}

const workspace = new URL(workspaceAddress);
const dnsName = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
if (
  workspace.protocol !== "https:" ||
  !dnsName.test(workspace.hostname) ||
  workspace.username ||
  workspace.password ||
  workspace.port ||
  workspace.search ||
  workspace.hash ||
  !["/", "/market"].includes(workspace.pathname)
) {
  throw new Error("The workspace link must be an HTTPS origin with path / or /market.");
}

const marker = "__FOLIOCREW_WORKSPACE_URL__";
const source = new URL("../landing/", import.meta.url);
const html = await readFile(new URL("index.html", source), "utf8");
if (html.split(marker).length !== 2) {
  throw new Error("The landing template must contain one workspace link placeholder.");
}

const outputPath = resolve(output);
await mkdir(outputPath);
await cp(source, outputPath, { recursive: true });
await writeFile(
  resolve(outputPath, "index.html"),
  html.replace(marker, () => workspace.href),
);
