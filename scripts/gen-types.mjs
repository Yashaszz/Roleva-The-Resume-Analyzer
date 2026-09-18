#!/usr/bin/env node
/**
 * Generate TypeScript types from the API's OpenAPI schema.
 *
 * The Pydantic models in apps/api are the single source of truth for the shape
 * of everything Roleva produces. Rather than hand-maintaining a parallel set of
 * TypeScript interfaces — which drift silently and are only noticed when the UI
 * renders undefined — the frontend's types are generated from that schema.
 *
 * Run after changing any domain model:
 *   pnpm gen:types
 *
 * The generated file is committed so CI and a fresh clone can typecheck without
 * needing a running backend.
 */

import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const API_DIR = join(ROOT, 'apps', 'api');
const OUT_DIR = join(ROOT, 'packages', 'contracts');
const SCHEMA_PATH = join(OUT_DIR, 'openapi.json');
const TYPES_PATH = join(ROOT, 'apps', 'web', 'lib', 'api-types.ts');

const PYTHON = process.platform === 'win32'
  ? join(API_DIR, '.venv', 'Scripts', 'python.exe')
  : join(API_DIR, '.venv', 'bin', 'python');

if (!existsSync(PYTHON)) {
  console.error(`No virtualenv at ${PYTHON}\nRun:  cd apps/api && python -m venv .venv && pip install -e ".[dev]"`);
  process.exit(1);
}

// Export by importing the app directly rather than starting a server — one
// less moving part, and it works in CI without binding a port.
console.log('Exporting OpenAPI schema from the FastAPI app...');
const schemaJson = execFileSync(
  PYTHON,
  [join('scripts', 'export_openapi.py')],
  { cwd: API_DIR, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 },
);

mkdirSync(OUT_DIR, { recursive: true });
writeFileSync(SCHEMA_PATH, schemaJson, 'utf8');

const schema = JSON.parse(schemaJson);
const schemaCount = Object.keys(schema.components?.schemas ?? {}).length;
const pathCount = Object.keys(schema.paths ?? {}).length;
console.log(`  ${pathCount} paths, ${schemaCount} schemas`);

// Called as a library rather than shelling out to the CLI: spawning pnpm.cmd
// is unreliable on Windows, and this avoids depending on shell resolution.
console.log('Generating TypeScript types...');
const { default: openapiTS, astToString } = await import('openapi-typescript');
const generated = astToString(await openapiTS(schema));

const banner = `/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Produced from the FastAPI app's OpenAPI schema by scripts/gen-types.mjs.
 * The Pydantic models in apps/api are the source of truth; edit those and
 * re-run \`pnpm gen:types\`.
 */

`;

writeFileSync(TYPES_PATH, banner + generated, 'utf8');
console.log(`Wrote ${TYPES_PATH}`);
