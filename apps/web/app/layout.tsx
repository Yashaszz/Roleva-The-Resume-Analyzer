import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Roleva",
  description:
    "See how well your resume matches a specific job — and exactly why, line by line.",
  // Analysis pages contain resume content, so nothing here should ever be
  // indexed. Per-page overrides can loosen this for genuinely public pages.
  robots: { index: false, follow: false },
};

// Typed explicitly rather than with Next's generated `LayoutProps`, which only
// exists after a build — CI typechecks before building.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col font-sans">{children}</body>
    </html>
  );
}
