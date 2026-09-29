import { coreHealthUrl } from "./health.js";

export type JsonFetcher = (input: string, init?: RequestInit) => Promise<Response>;

/** Build a core API URL from the health URL helper. */
export function coreApiUrl(coreUrl: string, path: string): string {
  const url = new URL(coreHealthUrl(coreUrl));
  url.pathname = path;
  return url.toString();
}

/** Read a JSON document from core. Network and HTTP failures stay explicit. */
export async function fetchJson(
  url: string,
  fetchImpl: JsonFetcher = fetch,
  init?: RequestInit,
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetchImpl(url, init);
  } catch (error) {
    const message = error instanceof Error ? error.message : "network request failed";
    throw new Error(`Unable to reach OMNE Core: ${message}`);
  }
  if (!response.ok) {
    throw new Error(`OMNE Core request failed with status ${response.status}`);
  }
  try {
    return await response.json();
  } catch {
    throw new Error("OMNE Core response was not JSON");
  }
}
