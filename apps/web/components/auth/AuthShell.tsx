/**
 * The frame every auth screen sits in.
 *
 * Auth is the first thing a user sees, and most products treat it as a form on
 * an empty page. This one puts the product's actual argument beside the form,
 * in display type, so the thirty seconds someone spends signing up also tells
 * them what they are signing up for.
 *
 * On a phone the argument moves below the form: the reason they opened the page
 * is to sign in, and making them scroll past a manifesto to reach a password
 * field would be a design that admires itself.
 */
import Link from "next/link";
import type { ReactNode } from "react";

export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="min-h-dvh flex flex-col lg:flex-row">
      {/* The form. First in the DOM so it is first for a keyboard and a
          screen reader, whatever the visual order. */}
      <main className="flex-1 flex flex-col justify-center px-6 py-12 sm:px-12 lg:px-16">
        <div className="w-full max-w-[400px] mx-auto lg:mx-0 flex flex-col gap-8">
          <Link
            href="/"
            className="display text-lg no-underline text-primary w-fit inline-flex items-center min-h-[44px] rounded-sm"
            aria-label="Roleva, home"
          >
            Roleva
          </Link>

          <div className="flex flex-col gap-2">
            <h1 className="display" style={{ fontSize: "var(--text-xl)" }}>
              {title}
            </h1>
            {subtitle ? (
              <p className="text-base text-secondary leading-normal">{subtitle}</p>
            ) : null}
          </div>

          {children}

          {footer ? <div className="text-sm text-secondary">{footer}</div> : null}
        </div>
      </main>

      {/* The argument. Decorative in the sense that nothing here is an action —
          but it is real text, selectable and readable, not an illustration. */}
      <aside className="lg:w-[46%] lg:max-w-[620px] bg-panel border-t lg:border-t-0 lg:border-l border-line-subtle px-6 py-12 sm:px-12 lg:px-14 flex flex-col justify-center gap-8">
        <p
          className="display max-w-[18ch]"
          style={{ fontSize: "var(--text-xl)", lineHeight: "var(--leading-tight)" }}
        >
          Every number Roleva gives you points at a line you wrote.
        </p>

        <div className="flex flex-col gap-5 max-w-[42ch]">
          <Point>
            Paste a job description. Roleva reads what it actually asks for, then looks
            for each requirement in your own words.
          </Point>
          <Point>
            Skills you list but never demonstrate are scored differently from skills you
            show. That gap is usually the reason for a rejection nobody explains.
          </Point>
          <Point>
            No score comes from a language model&rsquo;s opinion of you. The model reads;
            the arithmetic is code you can inspect.
          </Point>
        </div>
      </aside>
    </div>
  );
}

function Point({ children }: { children: ReactNode }) {
  return (
    <div className="flex gap-3">
      {/* A short thread stub — the product's own vocabulary, used as the bullet
          mark rather than a generic dot. */}
      <svg width="20" height="8" aria-hidden="true" className="shrink-0 mt-2.5">
        <line
          x1="0"
          y1="4"
          x2="20"
          y2="4"
          stroke="var(--thread-shown)"
          strokeWidth="var(--thread-width)"
        />
      </svg>
      <p className="text-sm text-secondary leading-normal m-0">{children}</p>
    </div>
  );
}
