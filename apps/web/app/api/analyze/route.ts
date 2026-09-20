/**
 * Proxies an analysis to the API, streaming the response straight through.
 *
 * The browser never learns the API's origin and never handles a bearer token:
 * it posts to this route, which attaches the session token and forwards on.
 * That is the reason the BFF layer exists at all.
 *
 * The body is piped rather than buffered. Buffering would hold an 8 MB upload
 * and the entire report in this function's memory, and — worse — would defeat
 * the streaming: the user would see nothing for thirty seconds and then
 * everything at once, which is exactly what the progress screen exists to avoid.
 */

import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { serverClient } from "@/lib/supabase";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

/** An analysis takes 20-50s, and a cold Render instance adds up to 60 more. */
export const maxDuration = 120;

export async function POST(request: NextRequest) {
  const store = await cookies();
  const supabase = serverClient({ getAll: () => store.getAll() });

  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) {
    return NextResponse.json(
      { code: "unauthorized", message: "Sign in to run an analysis." },
      { status: 401 },
    );
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE_URL}/analyze/stream`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${session.access_token}`,
        // The browser's multipart boundary is carried through unchanged;
        // regenerating it would invalidate the body being piped.
        "Content-Type": request.headers.get("content-type") ?? "multipart/form-data",
      },
      body: request.body,
      // Required by undici whenever a stream is used as a request body.
      duplex: "half",
    } as RequestInit & { duplex: "half" });
  } catch {
    // The API being unreachable is a real possibility on a free tier that
    // sleeps, and it deserves a sentence rather than a stack trace.
    return NextResponse.json(
      {
        code: "upstream_unavailable",
        message:
          "Couldn't reach the analysis service. It may be waking up — try again in a moment.",
      },
      { status: 503 },
    );
  }

  // Errors raised before the stream opens — quota, capacity, a rejected file —
  // arrive as ordinary JSON with a real status, and are passed through as such
  // so the client can handle them without parsing a stream.
  if (!upstream.ok) {
    const body = await upstream.text();
    return new NextResponse(body, {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json" },
    });
  }

  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      // Vercel buffers by default, which would hold every progress event until
      // the analysis finished.
      "X-Accel-Buffering": "no",
    },
  });
}
