import type { NextConfig } from "next";

/**
 * Security headers. 9.4.
 *
 * The threat this product actually faces is not exotic: it renders text taken
 * from a PDF somebody uploaded, and it holds a session that reads résumé data.
 * So the headers that matter are the ones that stop injected content becoming
 * script, and stop the session being usable from somewhere else.
 *
 * Each one is here because of a specific risk, not because a checklist listed
 * it — a header nobody can justify is a header that gets loosened the first
 * time it breaks something.
 */
const SECURITY_HEADERS = [
  /*
   * The important one. Résumé text reaches the DOM, and while React escapes it,
   * CSP is what turns "we escape everything" from a claim into a property.
   *
   * `'unsafe-inline'` on styles is required: next/font injects inline style
   * tags, and every component here styles through inline `style` attributes
   * for the token values. Scripts do NOT get it — `'strict-dynamic'` with the
   * nonce Next emits would be stricter still, and is the obvious next step once
   * there is a reason to spend the debugging time.
   */
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      // Next's runtime needs eval in development; the production build does not.
      process.env.NODE_ENV === "development"
        ? "script-src 'self' 'unsafe-eval' 'unsafe-inline'"
        : "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
      "font-src 'self' https://fonts.gstatic.com data:",
      "img-src 'self' data: blob:",
      // The API and Supabase. Nothing else — an injected fetch has nowhere to
      // send what it reads.
      "connect-src 'self' https://*.supabase.co https://*.supabase.in",
      "form-action 'self'",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "object-src 'none'",
      "upgrade-insecure-requests",
    ].join("; "),
  },

  // A report in an iframe on someone else's page is a clickjacking target, and
  // there is no legitimate reason to embed Roleva.
  { key: "X-Frame-Options", value: "DENY" },

  // Stops a PDF-shaped response being sniffed into something executable.
  { key: "X-Content-Type-Options", value: "nosniff" },

  // The referrer would otherwise carry a share token to whatever the reader
  // clicks next. Origin only, and nothing at all when leaving HTTPS.
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },

  // Roleva needs none of these. Denying them means an injected script cannot
  // ask for them either.
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
  },

  /*
   * HSTS. Two years, including subdomains.
   *
   * Deliberately without `preload`: preloading is effectively irreversible, and
   * committing a domain to HTTPS-only in a browser's built-in list is not a
   * decision to make from a config file before the domain is even live.
   */
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains",
  },
];

const nextConfig: NextConfig = {
  // Produced on every response; the server's version is not a fact visitors
  // need and is a fact scanners like.
  poweredByHeader: false,

  async headers() {
    return [
      { source: "/:path*", headers: SECURITY_HEADERS },
      {
        // Every page holds or can reach résumé content. The landing page opts
        // back in for itself.
        source: "/:path*",
        headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }],
      },
      {
        source: "/",
        headers: [{ key: "X-Robots-Tag", value: "index, follow" }],
      },
    ];
  },
};

export default nextConfig;
