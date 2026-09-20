/**
 * Panel, and the small parts that live inside one.
 *
 * The whole layout of this direction is panels on a strict grid — a panel is the
 * single container primitive, and it has no variants beyond padding. Cards with
 * shadows, gradients and rounded corners are what the brief ruled out; a panel
 * is a rectangle with a hairline.
 */
import type { ReactNode } from "react";

export function Panel({
  children,
  className = "",
  padded = true,
  as: Tag = "section",
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
  as?: "section" | "div" | "article" | "aside";
}) {
  return (
    <Tag
      className={`bg-panel border border-line-subtle rounded-sm ${
        padded ? "p-5" : ""
      } ${className}`}
    >
      {children}
    </Tag>
  );
}

/**
 * A panel's title.
 *
 * Always a mono label, never a heading-sized word. In an instrument the panel
 * titles are captions on dials; making them large would compete with the data,
 * which is the only thing on the page that should be loud.
 */
export function PanelTitle({
  children,
  right,
  id,
}: {
  children: ReactNode;
  right?: ReactNode;
  id?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4 mb-4">
      <h2 id={id} className="label">
        {children}
      </h2>
      {right}
    </div>
  );
}

/** A hairline. Subtle by default; `strong` when it carries meaning. */
export function Rule({ strong = false }: { strong?: boolean }) {
  return (
    <hr
      className={`border-0 h-px ${strong ? "bg-line-strong" : "bg-line-subtle"}`}
      aria-hidden="true"
    />
  );
}

/**
 * A mono label. Exposed as a component as well as a class so it can carry an
 * `id` for `aria-labelledby` without every caller writing the class list.
 */
export function Label({
  children,
  className = "",
  id,
}: {
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <span id={id} className={`label ${className}`}>
      {children}
    </span>
  );
}

/**
 * The evidence state mark: filled, half, or empty.
 *
 * This exists because **state must never be carried by colour alone.** Every
 * place the product says "demonstrated / listed / absent" shows this mark beside
 * the colour, so the meaning survives greyscale printing and the common forms of
 * colour blindness. Drawn as SVG rather than a character so it renders
 * identically on every platform.
 */
export function EvidenceMark({
  state,
  size = 10,
}: {
  state: "shown" | "listed" | "absent";
  size?: number;
}) {
  const label = { shown: "Demonstrated", listed: "Listed only", absent: "No evidence" }[state];

  return (
    <>
      <svg
        width={size}
        height={size}
        viewBox="0 0 10 10"
        aria-hidden="true"
        className="shrink-0"
        style={{ display: "block" }}
      >
        <circle cx="5" cy="5" r="4" fill="none" stroke="currentColor" strokeWidth="1.5" />
        {state === "shown" ? <circle cx="5" cy="5" r="2.5" fill="currentColor" /> : null}
        {state === "listed" ? (
          // A half-filled disc: visibly between the other two at a glance, and
          // still distinguishable from them at 10px.
          <path d="M5 1.5A3.5 3.5 0 0 1 5 8.5z" fill="currentColor" />
        ) : null}
      </svg>
      {/* The word behind the mark, for anyone who cannot see either. */}
      <span className="sr-only">{label}</span>
    </>
  );
}
