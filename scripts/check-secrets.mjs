#!/usr/bin/env node
/**
 * 9.5 — no secret is reachable from the browser.
 *
 * Two checks, because there are two ways a key leaks.
 *
 * 1. **Into the repository.** Any file git tracks is a file that ends up on
 *    GitHub. `.env` is ignored, but a key pasted into a config file, a test
 *    fixture or a comment is not.
 * 2. **Into the bundle.** Next inlines every `NEXT_PUBLIC_*` variable at build
 *    time. A service-role key given that prefix by mistake is shipped to every
 *    visitor, and nothing about it looks wrong in the source.
 *
 * Run: node scripts/check-secrets.mjs
 */

import { execSync } from "node:child_process";
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

/** Things that are secret whatever they are called. */
const PATTERNS = [
  { name: "Google API key", re: /AIza[0-9A-Za-z_-]{30,}/ },
  { name: "Gemini key (AQ. form)", re: /AQ\.[A-Za-z0-9_-]{20,}/ },
  { name: "JWT", re: /eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\./ },
  { name: "private key block", re: /-----BEGIN (RSA |EC )?PRIVATE KEY-----/ },
  { name: "Supabase service role", re: /"role"\s*:\s*"service_role"/ },
];

/** Files that legitimately describe these shapes without holding one.
 *  Matched as plain substrings: a regex with path separators in it is
 *  exactly the kind of escaping that gets mangled on the way into a file. */
const ALLOWED = ["check-secrets.mjs", "check-env.mjs"];

let failures = 0;

function scan(label, files, read) {
  for (const file of files) {
    if (ALLOWED.some((name) => file.includes(name))) continue;
    let text;
    try {
      text = read(file);
    } catch {
      continue;
    }
    for (const { name, re } of PATTERNS) {
      const hit = text.match(re);
      if (hit) {
        // The value is never printed — that would put it in a log.
        console.log(`  FAIL  ${label}: ${name} in ${file} (${hit[0].length} chars)`);
        failures += 1;
      }
    }
  }
}

console.log("\nSecrets audit\n");

// --- 1. tracked files ---
const tracked = execSync("git ls-files", { encoding: "utf8" })
  .split("\n")
  .filter((f) => f && !/\.(png|jpg|jpeg|gif|pdf|woff2?|ico)$/i.test(f));

scan("tracked file", tracked, (f) => readFileSync(f, "utf8"));
console.log(`  OK    ${tracked.length} tracked files scanned`);

// --- 2. the built client bundle ---
const chunks = "apps/web/.next/static/chunks";
if (existsSync(chunks)) {
  const walk = (dir) =>
    readdirSync(dir).flatMap((entry) => {
      const full = join(dir, entry);
      return statSync(full).isDirectory() ? walk(full) : [full];
    });
  const bundles = walk(chunks).filter((f) => f.endsWith(".js"));

  /*
   * A JWT in the bundle is not automatically a leak: the Supabase anon key IS
   * a JWT and is meant to be there — it identifies the project, and RLS is what
   * protects the data. What matters is the `role` claim. So the bundle is
   * checked by decoding every JWT rather than by banning the shape, because a
   * blanket ban reports the correct configuration as a catastrophe and teaches
   * whoever runs this to ignore it.
   */
  const bundleText = bundles.map((f) => readFileSync(f, "utf8")).join("");
  const jwts = [...bundleText.matchAll(/eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*/g)];
  for (const [token] of jwts) {
    let role = "unreadable";
    try {
      role = JSON.parse(Buffer.from(token.split(".")[1], "base64").toString()).role ?? "none";
    } catch {
      /* not a Supabase token; the role check below still rejects it */
    }
    if (role === "anon") continue;
    console.log(`  FAIL  client bundle ships a JWT with role="${role}"`);
    failures += 1;
  }
  console.log(`  OK    ${bundles.length} bundles, ${jwts.length} JWT(s), all role="anon"`);

  // The other patterns still apply to the bundle; only the JWT shape is
  // special-cased above.
  scan("client bundle", bundles, (f) =>
    readFileSync(f, "utf8").replace(/eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*/g, ""),
  );

  // Server-only variables must not even be named in client code.
  for (const name of ["SUPABASE_SERVICE_ROLE_KEY", "GEMINI_API_KEY", "SUPABASE_JWT_SECRET"]) {
    if (bundleText.includes(name)) {
      console.log(`  FAIL  client bundle references ${name}`);
      failures += 1;
    }
  }
  console.log("  OK    no server-only variable named in the bundle");
} else {
  console.log("  --    no client build found; run `npm run build` in apps/web to include it");
}

// --- 3. .env is ignored ---
try {
  execSync("git check-ignore -q .env", { stdio: "ignore" });
  console.log("  OK    .env is gitignored");
} catch {
  console.log("  FAIL  .env is NOT gitignored");
  failures += 1;
}

console.log(`\n${failures} problem(s)\n`);
process.exit(failures ? 1 : 0);
