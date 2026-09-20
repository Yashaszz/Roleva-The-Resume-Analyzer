"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AuthShell } from "@/components/auth/AuthShell";
import { Divider, GoogleButton } from "@/components/auth/GoogleButton";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { authMessage, browserClient } from "@/lib/supabase";
import { safeNext } from "@/lib/redirect";

export default function SignInPage() {
  return (
    // useSearchParams needs a Suspense boundary for static rendering.
    <Suspense fallback={null}>
      <SignIn />
    </Suspense>
  );
}

function SignIn() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    const supabase = browserClient();
    const { error: failure } = await supabase.auth.signInWithPassword({ email, password });

    if (failure) {
      setError(authMessage(failure));
      setBusy(false);
      return;
    }

    // refresh() so server components re-render with the new session before the
    // navigation lands — without it the destination renders as signed out once.
    router.replace(next);
    router.refresh();
  }

  return (
    <AuthShell
      title="Sign in"
      subtitle="Pick up where you left off, or start a new analysis."
      footer={
        <>
          No account?{" "}
          <Link href={`/sign-up${next !== "/analyze" ? `?next=${encodeURIComponent(next)}` : ""}`} className="text-shown">
            Create one
          </Link>
        </>
      }
    >
      <div className="flex flex-col gap-5">
        <GoogleButton next={next} />
        <Divider />

        {/* A real <form>, so Enter submits and password managers recognise it. */}
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
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />

          {error ? (
            <p role="alert" className="text-sm text-absent">
              {error}
            </p>
          ) : null}

          <Button type="submit" variant="primary" busy={busy} className="w-full">
            Sign in
          </Button>
        </form>

        <Link href="/reset-password" className="text-sm text-secondary w-fit">
          Forgotten your password?
        </Link>
      </div>
    </AuthShell>
  );
}
