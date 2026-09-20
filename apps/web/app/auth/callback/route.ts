/**
 * Where email confirmations and OAuth sign-ins land.
 *
 * Supabase sends the browser here with a one-time `code`. Exchanging it for a
 * session writes the auth cookies, which is why this has to be a route handler
 * rather than a page — a server component cannot set them.
 *
 * Excluded from the middleware matcher: running a session refresh against a
 * half-completed exchange races with this and can sign the user straight back
 * out.
 */

import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { safeNext } from "@/lib/redirect";
import { serverClient } from "@/lib/supabase";

export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const code = searchParams.get("code");
  const next = safeNext(searchParams.get("next"));

  // The provider reports its own failures this way — a declined consent screen,
  // a link opened twice. Carry the reason to the sign-in page rather than
  // silently landing the user on a form with no explanation.
  const providerError = searchParams.get("error_description") ?? searchParams.get("error");
  if (providerError) {
    const target = new URL("/sign-in", origin);
    target.searchParams.set("error", providerError.slice(0, 200));
    return NextResponse.redirect(target);
  }

  if (!code) {
    return NextResponse.redirect(new URL("/sign-in", origin));
  }

  const store = await cookies();
  const supabase = serverClient({
    getAll: () => store.getAll(),
    set: (name, value, options) => store.set(name, value, options),
  });

  const { error } = await supabase.auth.exchangeCodeForSession(code);

  if (error) {
    const target = new URL("/sign-in", origin);
    // Almost always an expired or already-used link.
    target.searchParams.set("error", "That link has expired. Try signing in again.");
    return NextResponse.redirect(target);
  }

  return NextResponse.redirect(new URL(next, origin));
}
