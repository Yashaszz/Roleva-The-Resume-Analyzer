import { NextResponse } from "next/server";

import { checkHealth } from "@/lib/api";

/**
 * Warm-up and readiness probe.
 *
 * Proxied rather than called directly from the browser so the backend origin
 * never appears in client code.
 */
export async function GET() {
  const status = await checkHealth();
  return NextResponse.json(status, {
    status: status.state === "down" ? 503 : 200,
    headers: { "cache-control": "no-store" },
  });
}
