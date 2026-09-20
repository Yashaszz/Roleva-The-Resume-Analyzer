/**
 * Loading and empty states.
 *
 * Two rules, both from the design record:
 *
 * 1. **A skeleton is the shape of the thing that is coming**, not a generic grey
 *    block. A skeleton that does not match its content causes a layout jump when
 *    the real thing arrives, which is worse than showing nothing.
 * 2. **Nothing pulses under `prefers-reduced-motion`.** The shimmer is a
 *    `motion-safe:` utility, so a reduced-motion user sees a still placeholder —
 *    which still communicates "not here yet" via its position and shape.
 */
import type { ReactNode } from "react";

const SHIMMER =
  "bg-raised rounded-sm motion-safe:animate-pulse " +
  "[animation-duration:1.6s]";

/** One line of text-shaped placeholder. */
export function SkeletonLine({ width = "100%", height = 14 }: { width?: string; height?: number }) {
  return <div className={SHIMMER} style={{ width, height }} aria-hidden="true" />;
}

/**
 * A score panel that has not arrived.
 *
 * Shaped like the real one — label, big number, unit — so the panel does not
 * change size when the value lands.
 */
export function SkeletonScore() {
  return (
    <div className="flex flex-col gap-3" aria-hidden="true">
      <SkeletonLine width="72px" height={10} />
      <SkeletonLine width="110px" height={34} />
      <SkeletonLine width="88px" height={12} />
    </div>
  );
}

/** The requirement map before it is populated. */
export function SkeletonGrid({ cells = 14 }: { cells?: number }) {
  return (
    <div className="grid grid-cols-4 sm:grid-cols-7 gap-2" aria-hidden="true">
      {Array.from({ length: cells }, (_, index) => (
        <div
          key={index}
          className={SHIMMER}
          style={{
            height: 62,
            // Staggered so the grid reads as one object filling in rather than
            // fourteen independent things flashing.
            animationDelay: `calc(${index} * var(--stagger-step))`,
          }}
        />
      ))}
    </div>
  );
}

/**
 * A region whose content is still loading.
 *
 * `aria-busy` plus a single live message, rather than announcing every skeleton:
 * a screen reader reading out nine placeholder shapes is noise, and the one
 * sentence a user needs is "this is loading".
 */
export function LoadingRegion({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div aria-busy="true" aria-live="polite">
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}

/**
 * An empty state.
 *
 * Says what is missing and what to do about it. Never a shrug — "No data" tells
 * the user nothing they did not already know from looking at the page.
 */
export function Empty({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-start gap-3 py-10">
      <p className="text-md text-primary font-medium">{title}</p>
      <p className="text-sm text-secondary leading-normal max-w-[46ch]">{detail}</p>
      {action}
    </div>
  );
}
