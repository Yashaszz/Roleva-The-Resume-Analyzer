"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthShell } from "@/components/auth/AuthShell";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { authMessage, browserClient } from "@/lib/supabase";

const MIN_PASSWORD = 8;

/**
 * Set a new password, having arrived from the emailed link.
 *
 * Supabase turns that link into a short-lived recovery session before this page
 * renders. So the first thing here is to establish whether that session exists:
 * without it, `updateUser` would fail with a message about an unauthenticated
 * request, which tells the user nothing about the real problem — that their link
 * has expired or was already used.
 */
export default function NewPasswordPage() {
  const router = useRouter();
  const [ready, setReady] = useState<"checking" | "ready" | "invalid">("checking");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    const supabase = browserClient();
    supabase.auth.getSession().then(({ data }) => {
      setReady(data.session ? "ready" : "invalid");
    });
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();

    if (password.length < MIN_PASSWORD) {
      setError(`Your password needs to be at least ${MIN_PASSWORD} characters.`);
      return;
    }
    if (password !== confirm) {
      setError("Those two passwords don't match.");
      return;
    }

    setBusy(true);
    setError(null);

    const supabase = browserClient();
    const { error: failure } = await supabase.auth.updateUser({ password });

    if (failure) {
      setError(authMessage(failure));
      setBusy(false);
      return;
    }

    setDone(true);
    setBusy(false);
  }

  if (ready === "checking") {
    return (
      <AuthShell title="One moment">
        <p className="text-sm text-muted">Checking your link…</p>
      </AuthShell>
    );
  }

  if (ready === "invalid") {
    return (
      <AuthShell
        title="That link has expired"
        subtitle="Reset links work once and last an hour."
        footer={
          <Link href="/reset-password" className="text-shown">
            Send a new one
          </Link>
        }
      >
        <p className="text-sm text-muted leading-normal">
          If you have already used this link to set a password, sign in with it instead.
        </p>
      </AuthShell>
    );
  }

  if (done) {
    return (
      <AuthShell title="Password changed" subtitle="You're signed in and ready to go.">
        <Button
          variant="primary"
          className="w-full"
          onClick={() => {
            router.replace("/analyze");
            router.refresh();
          }}
        >
          Start an analysis
        </Button>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Set a new password">
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <Input
          label="New password"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_PASSWORD}
          hint={`At least ${MIN_PASSWORD} characters.`}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <Input
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />

        {error ? (
          <p role="alert" className="text-sm text-absent">
            {error}
          </p>
        ) : null}

        <Button type="submit" variant="primary" busy={busy} className="w-full">
          Change password
        </Button>
      </form>
    </AuthShell>
  );
}
