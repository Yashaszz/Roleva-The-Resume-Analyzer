/**
 * Session refresh and route protection.
 *
 * Two jobs, and they have to happen in this order:
 *
 * 1. **Refresh the session.** Supabase access tokens last an hour. Only
 *    middleware can write the refreshed cookie back, so if this does not run on
 *    every request, users get signed out mid-analysis — after a thirty-second
 *    wait, which is the worst possible moment.
 * 2. **Guard the private routes.** A signed-out visitor to `/analyze` is sent to
 *    sign-in *with their destination remembered*, so signing in lands them where
 *    they were going rather than dumping them on a dashboard.
 *
 * This is a convenience, not the security boundary. The real boundaries are the
 * API's token verification and Postgres RLS — someone who skips the middleware
 * still cannot read a row that is not theirs.
 */

import { NextResponse, type NextRequest } from "next/server";

import { middlewareClient } from "@/lib/supabase";

/** Routes that require a signed-in user. Prefix match. */
const PRIVATE = ["/analyze", "/report", "/history", "/settings"];

/** Routes a signed-in user has no reason to see. */
const AUTH_ONLY = ["/sign-in", "/sign-up"];

export async function middleware(request: NextRequest) {
  // The response the client writes cookies to has to be the one returned.
  const response = NextResponse.next({ request });

  let user = null;
  try {
    const supabase = middlewareClient(request, response);
    // getUser, not getSession: getSession trusts the cookie, getUser verifies
    // it against the auth server. On a route guard that difference matters.
    const result = await supabase.auth.getUser();
    user = result.data.user;
  } catch {
    // Supabase unreachable or unconfigured. Treat the visitor as signed out
    // rather than failing the request — a sign-in page they can retry from is a
    // better outcome than a 500.
    user = null;
  }

  const { pathname } = request.nextUrl;
  const isPrivate = PRIVATE.some((path) => pathname === path || pathname.startsWith(`${path}/`));
  const isAuthOnly = AUTH_ONLY.some((path) => pathname.startsWith(path));

  if (isPrivate && !user) {
    const target = request.nextUrl.clone();
    target.pathname = "/sign-in";
    // Remember where they were going. Path only — a full URL here would be an
    // open redirect, and `next` is read back with the same restriction.
    target.searchParams.set("next", pathname);
    return NextResponse.redirect(target);
  }

  if (isAuthOnly && user) {
    const target = request.nextUrl.clone();
    target.pathname = "/analyze";
    target.search = "";
    return NextResponse.redirect(target);
  }

  return response;
}

export const config = {
  /*
   * Everything except static assets and the auth callback.
   *
   * The callback is excluded because it exchanges a code for a session and
   * writes its own cookies; running the refresh against a half-finished session
   * first produces a race that signs the user straight back out.
   */
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|auth/callback|.*\\.(?:svg|png|jpg|jpeg|gif|webp|woff2?)$).*)",
  ],
};
