import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";

import "./globals.css";

/*
 * One family in two voices, chosen in Phase 6. IBM Plex was drawn as a system
 * typeface for technical work: its mono companion shares metrics with the sans,
 * and its figures stay unambiguous at 10px — which matters when most of the page
 * is numbers.
 *
 * Weights are declared explicitly rather than loading the variable font: three
 * static weights is a smaller download than the full axis, and this design uses
 * exactly three.
 */
const sans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
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
    <html lang="en" className={`${sans.variable} ${mono.variable} h-full`}>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
