import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Mono, Public_Sans } from "next/font/google";

import "./globals.css";

/*
 * Three voices, chosen in Phase 6.
 *
 * Fraunces carries the whole difference between this and a generated dashboard:
 * a high-contrast serif at display size reads as editorial, and no default
 * arrives at it. Its optical-size axis means the 104px score and the 21px
 * heading are drawn for their sizes rather than scaled.
 *
 * Public Sans for body — neutral, legible, and specifically not Inter. IBM Plex
 * Mono for data that has to align in a column.
 */
const display = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  // Loaded as the variable font: `weight` and `axes` are mutually exclusive in
  // next/font, and the optical-size axis is the reason this face was chosen.
  // The whole weight range comes with it, so the CSS sets weight freely.
  axes: ["opsz"],
  style: ["normal", "italic"],
  display: "swap",
});

const sans = Public_Sans({
  variable: "--font-public-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

const mono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Roleva",
  description:
    "See how well your resume matches a specific job — and exactly why, line by line.",
  // Every analysis page contains resume content, so nothing is indexable by
  // default. A genuinely public page has to opt in for itself.
  robots: { index: false, follow: false },
};

// Typed explicitly rather than with Next's generated `LayoutProps`, which only
// exists after a build — CI typechecks before it builds.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${sans.variable} ${mono.variable} h-full`}>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
