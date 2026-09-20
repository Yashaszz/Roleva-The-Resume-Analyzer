/**
 * Settings. 7.29 — export, sign out, delete account.
 *
 * Short on purpose. The destructive actions get the most words, because those
 * are the ones where a user needs to know exactly what happens before it does,
 * and the moment to say so is before the click rather than in a toast after it.
 *
 * Deleting the account is behind a confirmation dialog that names what goes.
 * Deleting an analysis is on the report itself, where the thing being deleted
 * is in front of you — a delete button in a settings page acts on something the
 * user cannot see.
 */
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Shell } from "@/components/app/Shell";
import { Button } from "@/components/ui/Button";
import { Dialog, DialogClose } from "@/components/ui/Overlay";
import { Panel, PanelTitle } from "@/components/ui/Panel";
import { ToastProvider, useToast } from "@/components/ui/Toast";
import { browserClient } from "@/lib/supabase";

export default function SettingsPage() {
  return (
    <ToastProvider>
      <Shell>
        <main className="mx-auto w-full max-w-[720px] px-5 sm:px-8 py-10 flex flex-col gap-10">
          <h1 className="display" style={{ fontSize: "var(--text-xl)" }}>
            Settings
          </h1>

          <WhatIsStored />
          <ExportSection />
          <AccountSection />
        </main>
      </Shell>
    </ToastProvider>
  );
}

function WhatIsStored() {
  return (
    <section className="flex flex-col gap-3">
      <PanelTitle>What Roleva stores</PanelTitle>
      <Panel className="flex flex-col gap-3">
        <p className="text-base text-secondary leading-normal m-0">
          <strong className="text-primary">Your PDF is never stored.</strong> It is read
          in memory during the analysis and then gone — there is no upload folder and no
          bucket.
        </p>
        <p className="text-base text-secondary leading-normal m-0">
          What is kept is the structured information read out of it: your experience,
          projects, skills and the exact lines quoted as evidence. Plus the job
          descriptions you pasted and the reports themselves.
        </p>
        <p className="text-base text-secondary leading-normal m-0">
          Anonymous score samples are kept for the cohort comparisons, but they carry no
          user id — the table has no column for one, so nothing in them can be traced
          back to you.
        </p>
      </Panel>
    </section>
  );
}

function ExportSection() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function download() {
    setBusy(true);
    try {
      const response = await fetch("/api/proxy/me/export", { cache: "no-store" });
      if (!response.ok) throw new Error(String(response.status));

      const data = await response.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);

      // A plain anchor click: the file is built in the browser from a response
      // the user already has, so nothing new leaves the machine.
      const link = document.createElement("a");
      link.href = url;
      link.download = `roleva-export-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(url);

      toast("Export downloaded", "good");
    } catch {
      toast("Couldn't build your export. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="flex flex-col gap-3">
      <PanelTitle>Your data</PanelTitle>
      <Panel className="flex flex-col gap-4">
        <p className="text-base text-secondary leading-normal m-0">
          Download everything linked to your account as a JSON file — every analysis,
          every job description, everything read out of every resume.
        </p>
        <Button variant="secondary" onClick={download} busy={busy} className="w-full sm:w-auto sm:self-start">
          Download my data
        </Button>
      </Panel>
    </section>
  );
}

function AccountSection() {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function signOut() {
    await browserClient().auth.signOut();
    router.replace("/sign-in");
    router.refresh();
  }

  async function deleteAccount() {
    setBusy(true);
    try {
      const response = await fetch("/api/proxy/me", { method: "DELETE" });
      if (!response.ok && response.status !== 204) throw new Error(String(response.status));

      // The account is gone; the local session is now a token for a user that
      // does not exist. Clearing it avoids a confusing half-signed-in state.
      await browserClient().auth.signOut();
      router.replace("/sign-up");
      router.refresh();
    } catch {
      toast("We couldn't delete your account. Please try again.");
      setBusy(false);
    }
  }

  return (
    <section className="flex flex-col gap-3">
      <PanelTitle>Account</PanelTitle>
      <Panel className="flex flex-col gap-5">
        <div className="flex flex-col gap-3">
          <p className="text-base text-secondary leading-normal m-0">
            Signing out ends this session on this device.
          </p>
          <Button variant="secondary" onClick={signOut} className="w-full sm:w-auto sm:self-start">
            Sign out
          </Button>
        </div>

        <div className="h-px bg-line-subtle" />

        <div className="flex flex-col gap-3">
          <p className="text-base text-secondary leading-normal m-0">
            Deleting your account removes your profile, every analysis, every job
            description and everything read out of your resumes. It happens immediately
            and cannot be undone.
          </p>
          <Dialog
            trigger={
              <Button variant="danger" className="w-full sm:w-auto sm:self-start">
                Delete my account
              </Button>
            }
            title="Delete your account?"
            description="Your profile, your analyses, your job descriptions and everything read out of your resumes are removed immediately. This cannot be undone."
            footer={
              <>
                <DialogClose asChild>
                  <Button variant="ghost">Keep my account</Button>
                </DialogClose>
                <Button variant="danger" busy={busy} onClick={deleteAccount}>
                  Delete everything
                </Button>
              </>
            }
          />
        </div>
      </Panel>
    </section>
  );
}
