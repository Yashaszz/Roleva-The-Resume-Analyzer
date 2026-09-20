/**
 * Supabase clients — browser, server, and middleware.
 *
 * Three of them because the three places run in different worlds: the browser
 * keeps the session in cookies it can read, a server component can read those
 * cookies but not set them, and only middleware can refresh an expired token and
 * write the new one back. Using one client everywhere is how sessions start
 * silently expiring after an hour.
 *
 * The anon key is public by design — it appears in browser code. **RLS is what
 * protects the data**, which is why `supabase/migrations/0001` matters far more
 * than this file does, and why the live cross-user tests exist.
 */

import { createBrowserClient, createServerClient } from "@supabase/ssr";
import type { NextRequest, NextResponse } from "next/server";

/** Fails loudly at startup rather than producing a client that 401s later. */
function config() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !key) {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY must be set. " +
        "They are the project URL and the public anon key — not the service role key, " +
        "which must never reach the browser.",
    );
  }
  return { url, key };
}

/** In a client component. */
export function browserClient() {
  const { url, key } = config();
  return createBrowserClient(url, key);
}

/**
 * In a server component or route handler.
 *
 * `cookies()` is passed in rather than imported, because importing
 * `next/headers` here would make this module unusable from the browser build.
 */
export function serverClient(cookieStore: {
  getAll: () => { name: string; value: string }[];
  set?: (name: string, value: string, options?: Record<string, unknown>) => void;
}) {
  const { url, key } = config();

  return createServerClient(url, key, {
    cookies: {
      getAll: () => cookieStore.getAll(),
      setAll: (toSet) => {
        // A server component cannot set cookies. That is expected, not an
        // error: middleware has already refreshed the session for this
        // request, so there is nothing to write.
        if (!cookieStore.set) return;
        for (const { name, value, options } of toSet) {
          cookieStore.set(name, value, options);
        }
      },
    },
  });
}

/**
 * In middleware, where the session is actually refreshed.
 *
 * The response object has to be the one that is returned — writing cookies to a
 * response that gets discarded is the single most common way to end up with a
 * user who is signed in on the server and signed out in the browser.
 */
export function middlewareClient(request: NextRequest, response: NextResponse) {
  const { url, key } = config();

  return createServerClient(url, key, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (toSet) => {
        for (const { name, value, options } of toSet) {
          request.cookies.set(name, value);
          response.cookies.set(name, value, options);
        }
      },
    },
  });
}

/**
 * Turns a Supabase auth error into something a person can act on.
 *
 * Supabase's messages are written for developers — "Invalid login credentials",
 * "User already registered" — and several of them are ambiguous about what the
 * user should do next. Anything unrecognised falls through to its own text
 * rather than a generic apology, because a specific unknown error is still more
 * useful than a vague known one.
 */
export function authMessage(error: { message: string; status?: number } | null): string | null {
  if (!error) return null;

  const message = error.message.toLowerCase();

  if (message.includes("invalid login credentials")) {
    // Deliberately does not say which one was wrong: confirming that an email
    // exists is an account-enumeration leak.
    return "That email and password don't match. Check both and try again.";
  }
  if (message.includes("email not confirmed")) {
    return "Check your inbox and confirm your email address first.";
  }
  if (message.includes("user already registered") || message.includes("already been registered")) {
    return "There's already an account with that email. Try signing in instead.";
  }
  if (message.includes("password should be at least")) {
    return "Your password needs to be at least 8 characters.";
  }
  if (message.includes("rate limit") || error.status === 429) {
    return "Too many attempts. Wait a minute and try again.";
  }
  if (message.includes("failed to fetch") || message.includes("network")) {
    return "Couldn't reach the server. Check your connection and try again.";
  }

  return error.message;
}
