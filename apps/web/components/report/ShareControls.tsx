/**
 * Creating and revoking share links. 8.9.
 *
 * The visibility choice is made *before* the link exists, and each option says
 * plainly what it hands over. A share control that mints a link first and asks
 * about privacy afterwards has already made the decision for the user.
 *
 * "Full, redacted" is the default because most people sharing a report want
 * feedback on the analysis rather than to introduce themselves — and because a
 * default that leaks is a default most people will never change.
 */
"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog, DialogClose } from "@/components/ui/Overlay";
import { Panel } from "@/components/ui/Panel";
import { useToast } from "@/components/ui/Toast";

type Visibility = "scores_only" | "full_redacted" | "full_identified";

type Share = {
  token: string;
  analysis_id: string;
  visibility: Visibility;
  expires_at: string;
  view_count: number;
  active: boolean;
  revoked: boolean;
};

const MODES: { value: Visibility; label: string; detail: string }[] = [
  {
    value: "scores_only",
    label: "Scores only",
    detail: "The numbers and the verdict. No part of your resume is included.",
  },
  {
    value: "full_redacted",
    label: "Full report, redacted",
    detail: "Everything, with your name, contact details and employers removed.",
  },
  {
    value: "full_identified",
    label: "Full report, as you see it",
    detail: "The complete report including your name and employers.",
  },
];

export function ShareControls({ analysisId }: { analysisId: string }) {
  const toast = useToast();
  const [visibility, setVisibility] = useState<Visibility>("full_redacted");
  const [days, setDays] = useState(7);
  const [shares, setShares] = useState<Share[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refresh() {
    try {
      const response = await fetch("/api/proxy/shares", { cache: "no-store" });
      if (!response.ok) return;
      const data: { shares: Share[] } = await response.json();
      setShares((data.shares ?? []).filter((share) => share.analysis_id === analysisId));
    } catch {
      // A share list that will not load is not worth an error on a report page.
    }
  }

  async function create() {
    setBusy(true);
    try {
      const response = await fetch("/api/proxy/shares", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          analysis_id: analysisId,
          visibility,
          expires_in_days: days,
        }),
      });
      if (!response.ok) throw new Error(String(response.status));

      const created: { token: string } = await response.json();
      const url = `${window.location.origin}/shared/${created.token}`;

      try {
        await navigator.clipboard.writeText(url);
        toast("Link created and copied", "good");
      } catch {
        toast("Link created — copy it from the list below");
      }
      await refresh();
    } catch {
      toast("Couldn't create the link. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(token: string) {
    try {
      const response = await fetch(`/api/proxy/shares/${token}`, { method: "DELETE" });
      if (!response.ok && response.status !== 204) throw new Error();
      toast("Link revoked", "good");
      await refresh();
    } catch {
      toast("Couldn't revoke the link. Try again.");
    }
  }

  return (
    <Panel className="flex flex-col gap-5">
      <fieldset className="flex flex-col gap-3 border-0 p-0 m-0">
        <legend className="label p-0">What the link shows</legend>
        {MODES.map((mode) => (
          <label
            key={mode.value}
            className={
              "flex gap-3 p-3 rounded-sm cursor-pointer border " +
              "transition-colors [transition-duration:var(--duration-instant)] " +
              (visibility === mode.value
                ? "border-shown bg-good-bg"
                : "border-line-subtle hover:border-line-strong")
            }
          >
            <input
              type="radio"
              name="visibility"
              value={mode.value}
              checked={visibility === mode.value}
              onChange={() => setVisibility(mode.value)}
              className="mt-1 accent-[var(--evidence-shown)]"
            />
            <span className="flex flex-col gap-0.5">
              <span className="text-base text-primary">{mode.label}</span>
              <span className="text-sm text-muted leading-normal">{mode.detail}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <div className="flex flex-col sm:flex-row sm:items-end gap-3">
        <label className="flex flex-col gap-1.5 flex-1">
          <span className="label">Expires after</span>
          <select
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
            className="w-full bg-ground text-primary border border-line-strong rounded-sm px-3 py-2.5 text-base min-h-[44px]"
          >
            <option value={1}>1 day</option>
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days — the maximum</option>
          </select>
        </label>
        <Button variant="primary" onClick={create} busy={busy}>
          Create link
        </Button>
      </div>

      {shares.length > 0 ? (
        <div className="flex flex-col gap-2">
          <span className="label">Existing links</span>
          <ul className="flex flex-col m-0 p-0 list-none">
            {shares.map((share) => (
              <li
                key={share.token}
                className="flex items-center gap-3 py-3 border-b border-line-subtle last:border-b-0"
              >
                <span className="flex-1 min-w-0 flex flex-col gap-0.5">
                  <span className="text-sm text-primary">
                    {MODES.find((m) => m.value === share.visibility)?.label ??
                      share.visibility}
                  </span>
                  <span className="label">
                    {share.active
                      ? `expires ${new Date(share.expires_at).toLocaleDateString()}`
                      : share.revoked
                        ? "revoked"
                        : "expired"}
                    {" · "}
                    {share.view_count} {share.view_count === 1 ? "view" : "views"}
                  </span>
                </span>

                {share.active ? (
                  <>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={async () => {
                        const url = `${window.location.origin}/shared/${share.token}`;
                        try {
                          await navigator.clipboard.writeText(url);
                          toast("Copied", "good");
                        } catch {
                          toast("Couldn't copy — select the link manually");
                        }
                      }}
                    >
                      Copy
                    </Button>
                    <Dialog
                      trigger={
                        <Button variant="ghost" size="sm">
                          Revoke
                        </Button>
                      }
                      title="Revoke this link?"
                      description="Anyone who already has it will stop being able to open it, immediately."
                      footer={
                        <>
                          <DialogClose asChild>
                            <Button variant="ghost">Keep it</Button>
                          </DialogClose>
                          <DialogClose asChild>
                            <Button variant="danger" onClick={() => void revoke(share.token)}>
                              Revoke
                            </Button>
                          </DialogClose>
                        </>
                      }
                    />
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Panel>
  );
}
