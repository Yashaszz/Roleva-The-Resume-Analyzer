/**
 * The frame every signed-in page sits in.
 *
 * Deliberately not a navbar-and-logo strip. The bar carries the three things a
 * user needs — where they are, how many analyses they have left, and the way
 * back to starting one — and nothing else. A product with four screens does not
 * need a navigation system; it needs a line.
 */
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { QuotaMeter } from "@/components/app/QuotaMeter";
import type { ReactNode } from "react";

const LINKS = [
  { href: "/analyze", label: "New analysis" },
  { href: "/history", label: "History" },
  { href: "/settings", label: "Settings" },
];

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="min-h-dvh flex flex-col">
      <header className="border-b border-line-subtle">
        <div className="mx-auto w-full max-w-[1100px] px-5 sm:px-8 py-3 flex items-center gap-4 sm:gap-6">
          {/* The wordmark is a link home, so it needs a real target like any
              other. Text height alone put it at 23px. */}
          <Link
            href="/analyze"
            className="display text-lg no-underline text-primary shrink-0 inline-flex items-center min-h-[44px] rounded-sm"
          >
            Roleva
          </Link>

          {/* A real <nav> with a real current-page marker: `aria-current` is how
              a screen reader announces where you are, and it costs one word. */}
          <nav aria-label="Main" className="flex-1 min-w-0">
            <ul className="flex items-center gap-1 m-0 p-0 list-none overflow-x-auto">
              {LINKS.map((link) => {
                const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
                return (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      aria-current={active ? "page" : undefined}
                      className={
                        "inline-flex items-center min-h-[44px] px-3 text-sm no-underline rounded-sm whitespace-nowrap " +
                        "transition-colors [transition-duration:var(--duration-instant)] " +
                        (active
                          ? "text-primary font-medium"
                          : "text-muted hover:text-primary hover:bg-panel")
                      }
                    >
                      {link.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>

          <QuotaMeter />
        </div>
      </header>

      {children}
    </div>
  );
}
