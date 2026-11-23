/** Validate the fetch timestamp on an independently verified resource. */
import { deny } from "./crypto.mjs";

export function checkInputTimestamp(resource, now) {
  const age = now - Date.parse(resource.fetchedAt) / 1000;
  // Server and publication timestamps can differ by up to two seconds of precision.
  if (!Number.isFinite(age) || age < -2) deny("invalid_input_timestamp");
}
