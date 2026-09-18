/**
 * Server-side client for the Roleva API.
 *
 * Only ever imported from route handlers, never from a component. The backend
 * origin and any service credentials stay on the server: the browser talks to
 * this app's own routes, which proxy onward. That is the whole reason the BFF
 * layer exists.
 */

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export type HealthStatus =
  | { state: "ok"; environment: string }
  | { state: "waking" }
  | { state: "down"; reason: string };

/**
 * Wakes the API and reports whether it is ready.
 *
 * Render's free tier stops the instance after 15 minutes idle, and the first
 * request afterwards takes 30-60 seconds. The upload page calls this on load,
 * so the backend wakes up while the user is still choosing a file — by the time
 * they press Analyze it is warm. A slow response here is expected behaviour,
 * not an error, which is why "waking" is a distinct state.
 */
export async function checkHealth(timeoutMs = 8000): Promise<HealthStatus> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}/health`, {
      signal: controller.signal,
      cache: "no-store",
    });

    if (!response.ok) {
      return { state: "down", reason: `HTTP ${response.status}` };
    }

    const body = (await response.json()) as { environment?: string };
    return { state: "ok", environment: body.environment ?? "unknown" };
  } catch (error) {
    // A timeout almost always means a cold start rather than an outage.
    if (error instanceof Error && error.name === "AbortError") {
      return { state: "waking" };
    }
    return { state: "down", reason: "unreachable" };
  } finally {
    clearTimeout(timer);
  }
}
