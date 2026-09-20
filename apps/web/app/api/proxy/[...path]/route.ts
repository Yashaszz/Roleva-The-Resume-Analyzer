/**
 * One proxy for every non-streaming API call.
 *
 * The browser never learns the API's origin and never holds a bearer token; it
 * calls `/api/proxy/…` and this attaches the session. `/api/analyze` stays
 * separate because it streams and pipes a multipart body — different enough
 * that sharing code would make both harder to read.
 *
 * **Only these paths are forwarded.** A catch-all that passes anything through
 * is a proxy that will eventually forward something it should not; the
 * allow-list means adding a route is a deliberate act.
 */

import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { serverClient } from "@/lib/supabase";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

/** Path patterns the browser may reach, by method. */
const ALLOWED: { method: string; pattern: RegExp }[] = [
  { method: "GET", pattern: /^analyses$/ },
  { method: "GET", pattern: /^analyses\/[\w-]+$/ },
  { method: "DELETE", pattern: /^analyses\/[\w-]+$/ },
  { method: "GET", pattern: /^me\/quota$/ },
  { method: "GET", pattern: /^me\/export$/ },
  { method: "DELETE", pattern: /^me$/ },
];

async function forward(request: NextRequest, path: string[]) {
  const target = path.join("/");
  const method = request.method.toUpperCase();

  if (!ALLOWED.some((rule) => rule.method === method && rule.pattern.test(target))) {
    return NextResponse.json(
      { code: "not_found", message: "Not found." },
      { status: 404 },
    );
  }

  const store = await cookies();
  const supabase = serverClient({ getAll: () => store.getAll() });
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    return NextResponse.json(
      { code: "unauthorized", message: "Sign in to continue." },
      { status: 401 },
    );
  }

  const url = new URL(`${API_BASE_URL}/${target}`);
  url.search = request.nextUrl.search;

  try {
    const upstream = await fetch(url, {
      method,
      headers: { Authorization: `Bearer ${session.access_token}` },
      cache: "no-store",
    });

    // 204 carries no body, and constructing a Response with one for a 204 is a
    // runtime error rather than a no-op.
    if (upstream.status === 204) return new NextResponse(null, { status: 204 });

    const body = await upstream.text();
    return new NextResponse(body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch {
    return NextResponse.json(
      {
        code: "upstream_unavailable",
        message: "Couldn't reach the service. It may be waking up — try again in a moment.",
      },
      { status: 503 },
    );
  }
}

export async function GET(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await ctx.params).path);
}

export async function DELETE(request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await ctx.params).path);
}
