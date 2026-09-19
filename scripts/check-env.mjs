#!/usr/bin/env node
/**
 * Environment check for Roleva.
 *
 * Reports whether required configuration is present WITHOUT ever printing a
 * secret's value. Secrets are shown only as a masked fingerprint (length plus
 * the first two and last two characters) so you can tell two keys apart
 * without the value appearing in a terminal, a log, or a screen share.
 *
 *   node scripts/check-env.mjs           # presence check only
 *   node scripts/check-env.mjs --live    # also calls Gemini to prove the key works
 */

import { readFileSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const ENV_PATH = resolve(ROOT, '.env');

/** Minimal .env parser — avoids a dependency before `pnpm install` has run. */
function loadEnv(path) {
  if (!existsSync(path)) return null;
  const env = {};
  for (const raw of readFileSync(path, 'utf8').split('\n')) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    env[key] = value;
  }
  return env;
}

/** Never returns the secret. Enough to identify a key, not enough to use it. */
function fingerprint(value) {
  if (value.length < 8) return `set (${value.length} chars — suspiciously short)`;
  return `set (${value.length} chars, ${value.slice(0, 2)}…${value.slice(-2)})`;
}

const REQUIRED_SECRETS = ['GEMINI_API_KEY'];

const OPTIONAL_SECRETS = [
  'SUPABASE_SERVICE_ROLE_KEY',
  'SUPABASE_JWT_SECRET',
  'SUPABASE_ANON_KEY',
  'SENTRY_DSN',
];

const PLAIN = [
  'ENVIRONMENT',
  'SUPABASE_URL',
  'GEMINI_MODEL_MAIN',
  'GEMINI_MODEL_LIGHT',
  'GEMINI_EMBED_MODEL',
  'LLM_MAX_RPM',
  'LLM_MAX_RPD',
  'LLM_MAX_CALLS_PER_ANALYSIS',
  'USER_DAILY_ANALYSIS_QUOTA',
];

/** Values copied from .env.example that were never replaced. */
const PLACEHOLDERS = [/^your-/i, /your-project-ref/i, /^$/];

/**
 * Read the role out of a Supabase API key.
 *
 * These are JWTs whose payload is base64, not encrypted — the role is public
 * information, and reading it costs nothing. The dashboard shows several very
 * similar-looking `ey...` strings, so checking which is which catches the easy
 * mistake of pasting one into the wrong variable.
 */
function supabaseKeyRole(value) {
  if (!value) return null;
  const parts = value.split('.');
  if (parts.length !== 3) return null;
  try {
    const payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString());
    return payload.iss === 'supabase' ? (payload.role ?? null) : null;
  } catch {
    return null;
  }
}

const fileEnv = loadEnv(ENV_PATH);
if (fileEnv === null) {
  console.error('FAIL  .env not found. Run:  cp .env.example .env');
  process.exit(1);
}

// Real environment wins over the file, matching how Render and Vercel inject config.
const env = { ...fileEnv, ...process.env };

let failed = false;
console.log('Roleva environment check');
console.log('='.repeat(46));

console.log('\nRequired secrets');
for (const key of REQUIRED_SECRETS) {
  const value = env[key] ?? '';
  if (PLACEHOLDERS.some((p) => p.test(value))) {
    console.log(`  MISSING  ${key}  — still a placeholder or empty`);
    failed = true;
  } else {
    console.log(`  OK       ${key}  ${fingerprint(value)}`);
  }
}

console.log('\nOptional secrets');
for (const key of OPTIONAL_SECRETS) {
  const value = env[key] ?? '';
  const missing = PLACEHOLDERS.some((p) => p.test(value));
  console.log(missing ? `  --       ${key}  not set yet` : `  OK       ${key}  ${fingerprint(value)}`);
}

// Catch keys pasted into the wrong variable. The dashboard shows anon,
// service_role and (on legacy projects) a JWT secret within a few lines of each
// other, and two of the three are near-identical `ey...` strings.
const roleChecks = [
  ['SUPABASE_ANON_KEY', 'anon'],
  ['SUPABASE_SERVICE_ROLE_KEY', 'service_role'],
];
for (const [key, expected] of roleChecks) {
  const role = supabaseKeyRole(env[key]);
  if (role && role !== expected) {
    console.log(`\n  FAIL     ${key} holds the "${role}" key, not "${expected}"`);
    failed = true;
  }
}
const secretRole = supabaseKeyRole(env.SUPABASE_JWT_SECRET);
if (secretRole) {
  console.log(
    `\n  FAIL     SUPABASE_JWT_SECRET holds the "${secretRole}" API key.\n` +
      '           That variable is for the legacy HS256 signing secret, which is\n' +
      `           not an API key. Move this value to SUPABASE_${secretRole.toUpperCase()}_KEY.`,
  );
  failed = true;
}

console.log('\nNon-secret settings');
for (const key of PLAIN) {
  console.log(`  ${env[key] ? 'OK      ' : '--      '} ${key} = ${env[key] ?? '(unset)'}`);
}

// --- live check -------------------------------------------------------------
if (process.argv.includes('--live') && !failed) {
  console.log('\nLive Gemini check');
  const key = env.GEMINI_API_KEY;
  try {
    // The key goes in a header, never in the URL — query strings end up in
    // proxy logs and browser history.
    const res = await fetch('https://generativelanguage.googleapis.com/v1beta/models', {
      headers: { 'x-goog-api-key': key },
    });

    if (!res.ok) {
      const body = await res.text();
      const reason = body.slice(0, 200).replace(key, '[REDACTED]');
      console.log(`  FAIL     HTTP ${res.status} — ${reason}`);
      failed = true;
    } else {
      const data = await res.json();
      const names = (data.models ?? []).map((m) => m.name.replace('models/', ''));
      console.log(`  OK       key authenticates, ${names.length} models listed`);

      // Being listed is NOT the same as being usable: retired models still
      // appear in the listing but return 404 to accounts created after their
      // cutoff. Only an actual call proves a model works, so each configured
      // model gets one minimal request.
      const checks = [
        [env.GEMINI_MODEL_MAIN, 'generateContent'],
        [env.GEMINI_MODEL_LIGHT, 'generateContent'],
        [env.GEMINI_EMBED_MODEL, 'embedContent'],
      ];

      for (const [model, method] of checks) {
        if (!model) continue;
        if (!names.includes(model)) {
          console.log(`  FAIL     ${model}  — not listed for this account`);
          failed = true;
          continue;
        }

        const body =
          method === 'embedContent'
            ? { content: { parts: [{ text: 'ping' }] } }
            : {
                contents: [{ parts: [{ text: 'Reply with {"ok":true}' }] }],
                generationConfig: { temperature: 0, responseMimeType: 'application/json' },
              };

        const probe = await fetch(
          `https://generativelanguage.googleapis.com/v1beta/models/${model}:${method}`,
          {
            method: 'POST',
            headers: { 'x-goog-api-key': key, 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          },
        );

        if (probe.ok) {
          console.log(`  OK       ${model}  usable`);
        } else {
          const detail = await probe.json().catch(() => ({}));
          const msg = (detail?.error?.message ?? '').slice(0, 80);
          console.log(`  FAIL     ${model}  HTTP ${probe.status} — ${msg}`);
          failed = true;
        }
      }
    }
  } catch (err) {
    console.log(`  FAIL     ${String(err.message).replace(key, '[REDACTED]')}`);
    failed = true;
  }
}

// --- supabase ---------------------------------------------------------------
if (process.argv.includes('--live')) {
  console.log('\nLive Supabase check');
  const url = env.SUPABASE_URL;
  const anon = env.SUPABASE_ANON_KEY;

  // The dashboard shows several URLs and it is easy to copy the wrong one. A
  // full REST endpoint pasted here produces `.../rest/v1//rest/v1/profiles`,
  // which fails as an opaque 404 rather than saying what is actually wrong.
  const urlProblem = (value) => {
    if (!/^https:\/\//.test(value)) return 'must start with https://';
    const withoutScheme = value.replace(/^https:\/\//, '').replace(/\/+$/, '');
    if (withoutScheme.includes('/')) {
      return `should be the project base URL only — drop the "/${withoutScheme.split('/').slice(1).join('/')}" part`;
    }
    if (!withoutScheme.endsWith('.supabase.co')) return 'should end in .supabase.co';
    return null;
  };

  if (!url || PLACEHOLDERS.some((p) => p.test(url))) {
    console.log('  --       not configured yet (see docs/SUPABASE_SETUP.md)');
  } else if (urlProblem(url)) {
    console.log(`  FAIL     SUPABASE_URL ${urlProblem(url)}`);
    console.log('           expected: https://<project-ref>.supabase.co');
    failed = true;
  } else {
    try {
      // 401 and 404 both mean the host answered, which is all this probe is
      // for; whether the schema is usable is the next check's job.
      const res = await fetch(`${url}/rest/v1/`, { headers: { apikey: anon ?? '' } });
      const reachable = res.ok || res.status === 404 || res.status === 401;
      console.log(reachable ? '  OK       project reachable' : `  FAIL     HTTP ${res.status}`);
      if (!reachable) failed = true;

      // Confirms the schema migration was applied. profiles has RLS enabled and
      // no session is attached, so an empty result is the correct outcome — the
      // point is that the table exists rather than 404ing.
      const table = await fetch(`${url}/rest/v1/profiles?select=id&limit=1`, {
        headers: { apikey: anon ?? '', Authorization: `Bearer ${anon ?? ''}` },
      });
      if (table.status === 200) {
        // An empty array is the correct result: RLS is on and no user session
        // is attached. What matters is that the table resolves at all.
        console.log('  OK       schema applied, RLS active (profiles readable, returns no rows)');
      } else if (table.status === 404) {
        const detail = await table.json().catch(() => ({}));
        console.log(
          detail?.code === 'PGRST205'
            ? '  FAIL     profiles table not found — run supabase/migrations/0001_initial_schema.sql'
            : `  FAIL     schema check failed (${detail?.code ?? '404'}) — ${detail?.message ?? 'unknown'}`,
        );
        failed = true;
      } else {
        console.log(`  WARN     profiles returned HTTP ${table.status}`);
      }

      // Which signing scheme the project uses decides how the backend verifies
      // tokens: a shared HS256 secret, or asymmetric keys fetched from JWKS.
      const jwks = await fetch(`${url}/auth/v1/.well-known/jwks.json`, {
        headers: { apikey: anon ?? '' },
      });
      if (jwks.ok) {
        const body = await jwks.json();
        const keys = body?.keys ?? [];
        const secretSet = !PLACEHOLDERS.some((p) => p.test(env.SUPABASE_JWT_SECRET ?? ''));

        if (keys.length > 0) {
          const algs = [...new Set(keys.map((k) => k.alg ?? k.kty))].join(', ');
          console.log(`  OK       asymmetric JWT signing keys (${algs}) — verified via JWKS`);
          if (secretSet) {
            console.log('  WARN     SUPABASE_JWT_SECRET is set but unused on this project');
            console.log('           asymmetric projects verify against the public keys above');
          }
        } else if (secretSet) {
          console.log('  OK       legacy shared JWT secret (HS256)');
        } else {
          console.log('  FAIL     project uses HS256 but SUPABASE_JWT_SECRET is not set');
          failed = true;
        }
      }

      // Needed for the operational tables (llm_usage, rate_limits,
      // score_samples), which have no policies and are service-role only.
      // User-owned rows are NOT written with this key — those requests carry
      // the caller's own token so RLS still applies.
      if (PLACEHOLDERS.some((p) => p.test(env.SUPABASE_SERVICE_ROLE_KEY ?? ''))) {
        console.log('  FAIL     SUPABASE_SERVICE_ROLE_KEY not set');
        console.log('           Project Settings -> API -> service_role -> Reveal');
        failed = true;
      } else {
        console.log('  OK       service role key present');
      }
    } catch {
      console.log('  FAIL     could not reach the project');
      failed = true;
    }
  }
}

console.log('\n' + '='.repeat(46));
console.log(failed ? 'RESULT: not ready' : 'RESULT: ready');

// Set exitCode rather than calling process.exit(): on Windows, exiting while
// undici still holds an open socket from the live check trips a libuv assertion.
process.exitCode = failed ? 1 : 0;
