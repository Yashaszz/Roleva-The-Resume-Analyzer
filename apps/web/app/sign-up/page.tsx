"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AuthShell } from "@/components/auth/AuthShell";
import { Divider, GoogleButton } from "@/components/auth/GoogleButton";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { authMessage, browserClient } from "@/lib/supabase";
import { safeNext } from "@/lib/redirect";

/** Supabase's own floor is 6; 8 is the shortest worth recommending. */
const MIN_PASSWORD = 8;

export default function SignUpPage() {
  return (
    <Suspense fallback={null}>
      <SignUp />
    </Suspense>
  );
}

function SignUp() {
  const params = useSearchParams();
  const next = safeNext(params.get("next"));

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();

    // Checked here as well as by Supabase so the user finds out before a round
    // trip, and in words rather than as a validation code.
    if (password.length < MIN_PASSWORD) {
      setError(`Your password needs to be at least ${MIN_PASSWORD} characters.`);
      return;
    }

    setBusy(true);
    setError(null);

    const supabase = browserClient();
    const callback = new URL("/auth/callback", window.location.origin);
    callback.searchParams.set("next", next);

    const { error: failure } = await supabase.auth.signUp({
      email,
      password,
      options: { emailRedirectTo: callback.toString() },
    });

    if (failure) {
      setError(authMessage(failure));
      setBusy(false);
      return;
    }

    setSent(true);
    setBusy(false);
  }

  if (sent) {
    return (
      <AuthShell
        title="Check your email"
        subtitle={`We've sent a confirmation link to ${email}. Open it and you're in.`}
        footer={
          <>
            Wrong address?{" "}
            <button
              type="button"
              onClick={() => setSent(false)}
              className="text-shown bg-transparent border-0 p-0 cursor-pointer font-[inherit] text-[inherit]"
            >
              Use a different one
            </button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <div className="flex gap-3 p-4 bg-good-bg border-l-2 border-shown rounded-r-sm">
            <p className="text-sm text-secondary leading-normal m-0">
              The link expires in an hour. If it does not arrive in a few minutes, check
              your spam folder — confirmation mail from a new domain often lands there
              first.
            </p>
          </div>
          <p className="text-sm text-muted leading-normal">
            Roleva requires a confirmed address before an analysis runs. Unconfirmed
            accounts are the cheapest way to exhaust a shared free tier, and that quota is
            what keeps the product free for everyone.
          </p>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Create an account"
      subtitle="Free. Five analyses a day, which is more than anyone needs in a day."
      footer={
        <>
          Already have one?{" "}
          <Link href="/sign-in" className="text-shown">
            Sign in
          </Link>
        </>
      }
    >
      <div className="flex flex-col gap-5">
        <GoogleButton next={next} />
        <Divider />

        <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
          <Input
            label="Email"
            type="email"
            name="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Input
            label="Password"
            type="password"
            name="password"
            // new-password, so a password manager offers to generate one
            // instead of filling in an existing credential.
            autoComplete="new-password"
            required
            minLength={MIN_PASSWORD}
            hint={`At least ${MIN_PASSWORD} characters.`}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />

          {error ? (
            <p role="alert" className="text-sm text-absent">
              {error}
            </p>
          ) : null}

          <Button type="submit" variant="primary" busy={busy} className="w-full">
            Create account
          </Button>
        </form>

        <p className="text-sm text-muted leading-normal">
          Roleva stores what it reads out of your resume, never the file itself.
        </p>
      </div>
    </AuthShell>
  );
}
