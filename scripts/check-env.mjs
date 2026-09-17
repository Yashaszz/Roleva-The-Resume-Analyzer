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
      console.log(`  OK       key authenticates, ${names.length} models available`);

      for (const wanted of [env.GEMINI_MODEL_MAIN, env.GEMINI_MODEL_LIGHT, env.GEMINI_EMBED_MODEL]) {
        if (!wanted) continue;
        const found = names.some((n) => n === wanted || n.startsWith(wanted));
        console.log(`  ${found ? 'OK      ' : 'WARN    '} ${wanted}${found ? '' : '  — not in this account'}`);
      }
    }
  } catch (err) {
    console.log(`  FAIL     ${String(err.message).replace(key, '[REDACTED]')}`);
    failed = true;
  }
}

console.log('\n' + '='.repeat(46));
console.log(failed ? 'RESULT: not ready' : 'RESULT: ready');
process.exit(failed ? 1 : 0);
