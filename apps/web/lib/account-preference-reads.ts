import { boundedJson, untilSignal } from "./workspace-cache";

export const ACCOUNT_PREFERENCES_PATH = "/api/v2/preferences";
export type PreferenceReadMode = "cached" | "fresh";
export type PreferenceSection = "ui" | "language" | "currency";
type Sections = Record<PreferenceSection, Record<string, unknown> | null>;

const parts = ["ui", "language", "currency"] as const;
const MAX_SNAPSHOT_BYTES = 8192;
const MAX_AGE = 60_000;

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function sections(value: unknown): Sections {
  if (
    !object(value) ||
    Object.keys(value).length !== 4 ||
    !object(value.effective) ||
    !parts.every((part) => Object.hasOwn(value, part))
  )
    throw Error("Invalid preference snapshot");
  const parsed: Sections = { ui: null, language: null, currency: null };
  for (const part of parts) {
    const state = value[part];
    if (!object(state)) throw Error("Invalid preference snapshot");
    const { state: status, ...snapshot } = state;
    if (status === "available") parsed[part] = snapshot;
    else if (status !== "unavailable" || Object.keys(snapshot).length)
      throw Error("Invalid preference section");
  }
  return parsed;
}

type Flight = { controller: AbortController; promise: Promise<Sections> };

/** Stores only the current verified session's account preference response. */
export class AccountPreferenceReads {
  private owner: string | null = null;
  private cached: { sections: Sections; at: number } | null = null;
  private flight: Flight | null = null;

  clear() {
    this.owner = null;
    this.invalidate();
  }

  invalidate() {
    this.cached = null;
    this.flight?.controller.abort();
    this.flight = null;
  }

  async read(
    owner: string,
    part: PreferenceSection,
    mode: PreferenceReadMode,
    load: (signal: AbortSignal) => Promise<Response>,
    signal?: AbortSignal,
  ): Promise<Response> {
    if (signal?.aborted) throw Error("Cancelled preference read");
    if (this.owner !== owner) {
      this.clear();
      this.owner = owner;
    }
    const cached = this.cached;
    const age = cached ? Date.now() - cached.at : -1;
    if (mode === "cached" && cached && age >= 0 && age < MAX_AGE && cached.sections[part])
      return Response.json(cached.sections[part]);

    if (!this.flight) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 20_000);
      const promise = untilSignal(
        Promise.resolve()
          .then(() => load(controller.signal))
          .then(async (response) => {
            if (!response.ok || controller.signal.aborted) {
              void response.body?.cancel().catch(() => {});
              throw Error("Could not read preferences");
            }
            return sections(await boundedJson(response, MAX_SNAPSHOT_BYTES, controller.signal));
          }),
        controller.signal,
      )
        .then((value) => {
          if (this.flight?.controller === controller)
            this.cached = { sections: value, at: Date.now() };
          return value;
        })
        .finally(() => {
          clearTimeout(timeout);
          if (this.flight?.controller === controller) this.flight = null;
        });
      this.flight = { controller, promise };
    }
    const result = await untilSignal(this.flight.promise, signal);
    if (this.owner !== owner || signal?.aborted) throw Error("Cancelled preference read");
    return result[part] ? Response.json(result[part]) : new Response(null, { status: 503 });
  }
}
