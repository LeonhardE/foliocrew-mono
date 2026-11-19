import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { digest } from "../dist/core.mjs";

const vector = JSON.parse(
  await readFile(
    new URL("../../../services/common/tests/fixtures/private_resources.json", import.meta.url),
    "utf8",
  ),
);

test("the existing browser canonical digest matches the additive private-resource vectors", async () => {
  assert.equal(await digest(vector.request), vector.decision.requestDigest);
  assert.equal(await digest(vector.recovery), vector.evidence.requestDigest);
  assert.equal(await digest(vector.index.toReversed()), vector.evidence.sourcesDigest);
  assert.notEqual(
    await digest({ ...vector.request, attemptId: "different_attempt_id_0001" }),
    vector.decision.requestDigest,
  );
});
