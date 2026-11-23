import assert from "node:assert/strict";
import { checkInputTimestamp } from "../agent-client/src/policy.mjs";

const fetchedAt = "1970-01-01T00:16:40Z";
checkInputTimestamp({ fetchedAt }, 1000);
checkInputTimestamp({ fetchedAt }, 998);
checkInputTimestamp({ fetchedAt }, Date.parse("2026-11-22T23:37:00Z") / 1000);
for (const [timestamp, now] of [
  [fetchedAt, 997.9],
  ["invalid", 1000],
]) {
  assert.throws(
    () => checkInputTimestamp({ fetchedAt: timestamp }, now),
    (error) => error.code === "invalid_input_timestamp",
  );
}
