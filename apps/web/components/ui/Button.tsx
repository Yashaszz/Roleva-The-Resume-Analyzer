/**
 * Button.
 *
 * Four variants, and the restraint is the point: a product with eight button
 * styles has no button styles. Every one of these is a real `<button>` or
 * `<a href>` — never a div with an onClick, which Tab skips and a screen reader
 * announces as nothing.
 *
 * The 44px minimum height is not a suggestion. It is the smallest target a
 * thumb reliably hits, and most of Roleva's users will be on a phone.
 */
"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "md" | "sm";

const BASE =
  "inline-flex items-center justify-center gap-2 font-medium " +
  "rounded-sm border transition-colors " +
  "disabled:opacity-50 disabled:cursor-not-allowed " +
  // Duration comes from the token, so prefers-reduced-motion zeroes it without
  // this component knowing the media query exists.
  "[transition-duration:var(--duration-instant)] " +
  "[transition-timing-function:var(--ease-out)]";

const VARIANTS: Record<Variant, string> = {
  // The signal colour, used here because a primary action is the one place a
  // filled accent earns its space.
  primary:
    "bg-shown-bg text-shown-text border-transparent hover:brightness-110 active:brightness-95",
  secondary:
    "bg-panel text-primary border-line-strong hover:bg-raised active:bg-panel",
  ghost:
    "bg-transparent text-secondary border-transparent hover:bg-panel hover:text-primary",
  // Destructive actions are outlined rather than filled. A filled red button is
  // easy to hit by accident, and everything using this variant deletes something.
  danger:
    "bg-transparent text-absent-text border-absent-line hover:bg-absent-bg",
};

const SIZES: Record<Size, string> = {
  md: "min-h-[44px] px-4 text-sm",
  // Only for dense toolbars. Still 36px, still above the point where a target
  // becomes genuinely hard to hit.
  sm: "min-h-[36px] px-3 text-xs",
};

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  /** Renders the label but shows a busy state and blocks interaction. */
  busy?: boolean;
  children: ReactNode;
};

export function Button({
  variant = "secondary",
  size = "md",
  busy = false,
  className = "",
  children,
  disabled,
  ...rest
}: Props) {
  return (
    <button
      type="button"
      // `aria-busy` rather than swapping the label for a spinner: a label that
      // disappears mid-action loses the user's place, and a screen reader that
      // was mid-sentence starts again.
      aria-busy={busy || undefined}
      disabled={disabled || busy}
      className={`${BASE} ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...rest}
    >
      {busy ? <Spinner /> : null}
      {children}
    </button>
  );
}

/**
 * A link that looks like a button.
 *
 * Separate component rather than an `as` prop, because the two have genuinely
 * different semantics: one performs an action, the other goes somewhere, and
 * conflating them produces buttons that cannot be opened in a new tab.
 */
export function ButtonLink({
  href,
  variant = "secondary",
  size = "md",
  className = "",
  children,
  ...rest
}: {
  href: string;
  variant?: Variant;
  size?: Size;
  className?: string;
  children: ReactNode;
} & React.AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <a
      href={href}
      className={`${BASE} ${VARIANTS[variant]} ${SIZES[size]} no-underline ${className}`}
      {...rest}
    >
      {children}
    </a>
  );
}

/**
 * The only looping animation in the product.
 *
 * It exists because a button that has been pressed and shows nothing reads as
 * broken. Under `prefers-reduced-motion` the duration token is zero, so the
 * arc holds still and the busy state is carried by `aria-busy` and the dimmed
 * appearance instead.
 */
function Spinner() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className="motion-safe:animate-spin"
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2.5" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}
