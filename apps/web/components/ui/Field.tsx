/**
 * Form fields.
 *
 * Every input has a real `<label>` with a real `for`. Placeholder-as-label is
 * the single most common accessibility failure in modern forms: it vanishes the
 * moment someone types, which is exactly when they need it, and screen readers
 * treat it inconsistently.
 *
 * Errors are wired with `aria-describedby` and `aria-invalid`, so the message is
 * announced when focus lands on the field rather than only being visible.
 */
"use client";

import type { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";
import { useId } from "react";

const CONTROL =
  "w-full bg-ground text-primary border border-line-strong rounded-sm " +
  "px-3 py-2.5 text-base " +
  "placeholder:text-muted " +
  "transition-colors [transition-duration:var(--duration-instant)] " +
  "hover:border-[var(--evidence-listed-line)] " +
  "aria-[invalid=true]:border-absent-line " +
  "disabled:opacity-50";

type FieldShellProps = {
  label: string;
  /** Shown under the label. For guidance, not for the label itself. */
  hint?: string;
  error?: string;
  /** Rendered at the right of the label row — a counter, a meter. */
  meta?: ReactNode;
  required?: boolean;
  children: (ids: { id: string; describedBy: string | undefined }) => ReactNode;
};

function FieldShell({ label, hint, error, meta, required, children }: FieldShellProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;

  // Both are announced when present. The error comes second so it is the last
  // thing heard, which is the part that needs acting on.
  const describedBy =
    [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="label">
          {label}
          {required ? (
            <span className="text-absent" aria-hidden="true">
              {" *"}
            </span>
          ) : null}
        </label>
        {meta}
      </div>

      {hint ? (
        <p id={hintId} className="text-sm text-muted">
          {hint}
        </p>
      ) : null}

      {children({ id, describedBy })}

      {error ? (
        // role="alert" so a validation failure is announced immediately rather
        // than waiting for focus to reach the field.
        <p id={errorId} role="alert" className="text-sm text-absent">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function Input({
  label,
  hint,
  error,
  meta,
  className = "",
  ...rest
}: {
  label: string;
  hint?: string;
  error?: string;
  meta?: ReactNode;
} & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <FieldShell label={label} hint={hint} error={error} meta={meta} required={rest.required}>
      {({ id, describedBy }) => (
        <input
          id={id}
          aria-describedby={describedBy}
          aria-invalid={error ? true : undefined}
          className={`${CONTROL} ${className}`}
          {...rest}
        />
      )}
    </FieldShell>
  );
}

export function Textarea({
  label,
  hint,
  error,
  meta,
  className = "",
  ...rest
}: {
  label: string;
  hint?: string;
  error?: string;
  meta?: ReactNode;
} & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <FieldShell label={label} hint={hint} error={error} meta={meta} required={rest.required}>
      {({ id, describedBy }) => (
        <textarea
          id={id}
          aria-describedby={describedBy}
          aria-invalid={error ? true : undefined}
          className={`${CONTROL} resize-y min-h-[160px] leading-normal ${className}`}
          {...rest}
        />
      )}
    </FieldShell>
  );
}

/**
 * A length meter for the job-description field.
 *
 * Three states rather than a percentage bar, because what the user needs to know
 * is not "how full is this" but "is this enough yet". The state is carried by the
 * words as well as the colour — a bar that only changes hue tells a
 * colour-blind user nothing.
 */
export function LengthMeter({
  length,
  min,
  good,
}: {
  length: number;
  min: number;
  good: number;
}) {
  const state = length < min ? "short" : length < good ? "thin" : "ok";

  const copy = {
    short: `${min - length} more characters needed`,
    thin: "Enough to analyse, but more detail gives a better result",
    ok: "Good length",
  }[state];

  const colour = {
    short: "text-absent",
    thin: "text-capped",
    ok: "text-shown",
  }[state];

  return (
    <span className={`text-2xs font-mono uppercase tracking-[var(--tracking-label)] ${colour}`}>
      {/* The count is always available; the judgement is the part that changes. */}
      <span className="numeric">{length}</span>
      {" — "}
      {copy}
    </span>
  );
}
