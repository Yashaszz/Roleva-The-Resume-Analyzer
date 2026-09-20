/**
 * Sign in with Google.
 *
 * Placed above the email form rather than below it. Most people who have the
 * option take it, and burying the one-click path under a form they will not
 * fill in is a small daily tax on everyone.
 *
 * The button is hidden entirely when Google OAuth is not configured for the
 * project — an OAuth button that returns "provider is not enabled" is worse
 * than no button, because the user assumes they did something wrong.
 */
"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { authMessage, browserClient } from "@/lib/supabase";

/**
 * Whether Google sign-in is configured for this deployment.
 *
 * Read in one place, because both the button AND the "or" divider depend on it.
 * They were separate at first, and the result was a lone "or" with nothing above
 * it — the kind of small wrongness that makes a page look broken even though
 * every individual piece is correct.
 *
 * `process.env` is inlined at build time, so this cannot be a variable lookup.
 */
export const googleEnabled = process.env.NEXT_PUBLIC_GOOGLE_OAUTH_ENABLED === "true";

export function GoogleButton({ next }: { next?: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!googleEnabled) return null;

  async function signIn() {
    setBusy(true);
    setError(null);

    const supabase = browserClient();
    const callback = new URL("/auth/callback", window.location.origin);
    if (next) callback.searchParams.set("next", next);

    const { error: failure } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: callback.toString() },
    });

    if (failure) {
      setError(authMessage(failure));
      setBusy(false);
      return;
    }
    // On success the browser navigates away; leaving `busy` set avoids a flash
    // of an enabled button during the redirect.
  }

  return (
    <div className="flex flex-col gap-2">
      <Button variant="secondary" onClick={signIn} busy={busy} className="w-full">
        {busy ? null : <GoogleMark />}
        Continue with Google
      </Button>
      {error ? (
        <p role="alert" className="text-sm text-absent">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** Google's mark, in its own colours — the one place brand colour is allowed. */
function GoogleMark() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" className="shrink-0">
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.65l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.11a6.6 6.6 0 0 1 0-4.22V7.05H2.18a11 11 0 0 0 0 9.9l3.66-2.84z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1a11 11 0 0 0-9.82 6.05l3.66 2.84c.87-2.6 3.3-4.51 6.16-4.51z"
      />
    </svg>
  );
}

/**
 * "or" with a rule either side.
 *
 * Renders nothing when there is nothing to separate it from. Marked decorative
 * so it is not read aloud.
 */
export function Divider() {
  if (!googleEnabled) return null;

  return (
    <div className="flex items-center gap-3" aria-hidden="true">
      <span className="h-px flex-1 bg-line-subtle" />
      <span className="label">or</span>
      <span className="h-px flex-1 bg-line-subtle" />
    </div>
  );
}
