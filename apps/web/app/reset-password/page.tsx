"use client";

import Link from "next/link";
import { useState } from "react";

import { AuthShell } from "@/components/auth/AuthShell";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { authMessage, browserClient } from "@/lib/supabase";

/**
 * Request a reset link.
 *
 * The confirmation is deliberately the same whether or not an account exists.
 * "No account with that email" is an account-enumeration oracle: anyone can
 * test a list of addresses against it and learn which people use the product.
 */
export default function ResetPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    const supabase = browserClient();
    const { error: failure } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: new URL("/reset-password/new", window.location.origin).toString(),
    });

    // Network and rate-limit failures are still reported: those are about the
    // request, not about whether the address is registered.
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
        subtitle={`If there's an account for ${email}, a reset link is on its way.`}
        footer={
          <Link href="/sign-in" className="text-shown">
            Back to sign in
          </Link>
        }
      >
        <p className="text-sm text-muted leading-normal">
          The link works once and expires in an hour.
        </p>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Reset your password"
      subtitle="We'll email you a link to set a new one."
      footer={
        <Link href="/sign-in" className="text-shown">
          Back to sign in
        </Link>
      }
    >
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

        {error ? (
          <p role="alert" className="text-sm text-absent">
            {error}
          </p>
        ) : null}

        <Button type="submit" variant="primary" busy={busy} className="w-full">
          Send the link
        </Button>
      </form>
    </AuthShell>
  );
}
