export const CONNECTION_CONTRACT = "folioview.agent-workspace.v2.0";

export class ConnectionError extends Error {
  constructor(readonly code: string) {
    super(code);
  }
}
export const object = (value: unknown): value is Record<string, any> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
export const exact = (value: unknown, names: string[]): value is Record<string, any> =>
  object(value) &&
  Object.keys(value).length === names.length &&
  names.every((name) => Object.hasOwn(value, name));
export const identifier = (value: unknown): value is string =>
  typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(value);
