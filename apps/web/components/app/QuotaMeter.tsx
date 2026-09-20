/**
 * "3 of 5 analyses left today". 7.30.
 *
 * Shown always, not only when it is running out. A limit a user discovers by
 * hitting it is a limit they experience as a failure; one they can see is just
 * a fact about the product. The free tier is the reason Roleva costs nothing,
 * and being quiet about it until it bites would be the wrong trade.
 *
 * Reading the quota must not spend one, which is why the API reads the counter
 * rather than incrementing it — the increment belongs to the analysis.
 */
"use client";

import { useEffect, useState } from "react";

type Quota = { used: number; limit: number; remaining: number };

export function QuotaMeter() {
  const [quota, setQuota] = useState<Quota | null>(null);

  useEffect(() => {
    let cancelled = false;

    fetch("/api/proxy/me/quota", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((data: Quota | null) => {
        if (!cancelled && data) setQuota(data);
      })
      .catch(() => {
        // A quota display that cannot load is not worth a visible error. The
        // analysis itself reports the real limit if one is hit.
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // Nothing rather than a placeholder: a skeleton for one short line draws more
  // attention to itself than the line it is standing in for.
  if (!quota) return null;

  const spent = quota.remaining === 0;

  return (
    <span
      className={`hidden sm:flex items-center gap-2 shrink-0 text-2xs font-mono uppercase tracking-[var(--tracking-label)] ${
        spent ? "text-capped" : "text-muted"
      }`}
    >
      {/* The pips are decorative; the sentence beside them is the information,
          and it is what a screen reader reads. */}
      <span className="flex gap-1" aria-hidden="true">
        {Array.from({ length: quota.limit }, (_, index) => (
          <span
            key={index}
            className={`w-1.5 h-1.5 rounded-full ${
              index < quota.remaining ? "bg-shown" : "bg-line-strong"
            }`}
          />
        ))}
      </span>
      <span>
        {spent
          ? "none left today"
          : `${quota.remaining} of ${quota.limit} left today`}
      </span>
    </span>
  );
}
