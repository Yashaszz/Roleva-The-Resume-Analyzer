#!/usr/bin/env node
/**
 * WCAG contrast check for the Roleva palette.
 *
 * Gate 6 requires the palette to pass AA *before any screen is built*, which is
 * the only order that saves work: discovering that your muted grey is illegible
 * after forty components use it means editing forty components.
 *
 * This reads the real token file rather than a copy of the values, resolves
 * `var()` references, and checks every text-on-background pair the design
 * actually uses. A pair that is not listed here is a pair nobody has verified,
 * so the list is the contract: adding a new combination to the UI means adding
 * it here.
 *
 * Run: node scripts/check-contrast.mjs
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const TOKENS = join(here, "..", "apps", "web", "app", "tokens.css");

/* ------------------------------------------------------------------ parse -- */

function parseTokens(css) {
  const raw = {};
  // Only the :root block — the reduced-motion override redefines durations.
  const root = css.slice(css.indexOf(":root"), css.indexOf("@media"));
  for (const [, name, value] of root.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    raw[name] = value.trim();
  }

  // Resolve var() chains so semantic names carry real colours.
  const resolve = (value, depth = 0) => {
    if (depth > 10) return value;
    const match = value.match(/^var\((--[\w-]+)\)$/);
    if (!match) return value;
    const target = raw[match[1]];
    return target === undefined ? value : resolve(target, depth + 1);
  };

  const resolved = {};
  for (const [name, value] of Object.entries(raw)) resolved[name] = resolve(value);
  return resolved;
}

/* --------------------------------------------------------------- contrast -- */

function toRgb(hex) {
  const clean = hex.trim().replace("#", "");
  const full =
    clean.length === 3
      ? clean
          .split("")
          .map((c) => c + c)
          .join("")
      : clean;
  if (!/^[0-9a-f]{6}$/i.test(full)) return null;
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16));
}

/** Relative luminance, per WCAG 2.1. */
function luminance([r, g, b]) {
  const channel = (v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function ratio(fg, bg) {
  const a = luminance(fg);
  const b = luminance(bg);
  const [light, dark] = a > b ? [a, b] : [b, a];
  return (light + 0.05) / (dark + 0.05);
}

/* ------------------------------------------------------------------ pairs -- */

/**
 * Every combination the design puts on screen.
 *
 * `large` marks text at 24px+ (or 19px+ bold), which AA allows at 3:1. It is
 * used sparingly and never for anything small enough to be doubted.
 */
const PAIRS = [
  // --- body text on the two surfaces ---
  ["--text-primary", "--surface-canvas", "primary text on the canvas"],
  ["--text-primary", "--surface-panel", "primary text on a panel"],
  ["--text-secondary", "--surface-panel", "secondary text on a panel"],
  ["--text-secondary", "--surface-canvas", "secondary text on the canvas"],
  ["--text-muted", "--surface-panel", "muted labels on a panel"],
  ["--text-muted", "--surface-canvas", "muted labels on the canvas"],
  ["--text-primary", "--surface-raised", "primary text on a raised cell"],

  // --- the evidence vocabulary ---
  ["--evidence-shown", "--surface-canvas", "'demonstrated' as text"],
  ["--evidence-shown", "--surface-panel", "'demonstrated' as text on a panel"],
  ["--evidence-shown-text", "--evidence-shown-bg", "label inside a demonstrated cell"],
  ["--evidence-listed-text", "--evidence-listed-bg", "label inside a listed-only cell"],
  ["--evidence-absent-text", "--evidence-absent-bg", "label inside an absent cell"],
  ["--evidence-absent-text", "--surface-panel", "'absent' as text on a panel"],

  // --- status ---
  ["--status-capped", "--surface-panel", "the capped warning's text"],
  ["--status-capped", "--status-capped-bg", "capped text in its own callout"],
  ["--status-good", "--status-good-bg", "good text in its own callout"],

  // --- the big number, which is large text but should not need the allowance ---
  ["--status-capped", "--surface-panel", "the overall score when capped", { large: true }],

  // --- inverse (a primary button) ---
  ["--text-on-inverse", "--surface-inverse", "text on an inverse button"],
  ["--text-on-signal", "--evidence-shown", "text on a signal button"],
];

/* ------------------------------------------------------------------- run --- */

/**
 * Non-text contrast, WCAG 1.4.11. A cell's fill or outline is what tells the
 * user which state it is in, so it is a "graphical object required to
 * understand content" and needs 3:1 against what it sits on — not the 4.5:1 a
 * label needs, but not nothing either. This is the check that caught the first
 * palette: a listed-only teal dark enough to hold light text was too dark for
 * its own cell to be visible.
 */
const SHAPES = [
  ["--evidence-shown-bg", "--surface-panel", "a demonstrated cell against its panel"],
  ["--evidence-listed-line", "--surface-panel", "a listed-only cell's outline"],
  ["--evidence-absent-line", "--surface-panel", "an absent cell's outline"],
  ["--line-strong", "--surface-panel", "a hairline that has to be seen"],
  ["--focus-ring", "--surface-canvas", "the focus ring on the canvas"],
  ["--focus-ring", "--surface-panel", "the focus ring on a panel"],
  ["--status-capped", "--surface-panel", "the capped marker"],
];

const tokens = parseTokens(readFileSync(TOKENS, "utf8"));

let failures = 0;
let warnings = 0;
const rows = [];

const ALL = [
  ...PAIRS.map((pair) => [...pair.slice(0, 3), { ...(pair[3] ?? {}) }]),
  ...SHAPES.map(([fg, bg, label]) => [fg, bg, label, { shape: true }]),
];

for (const [fgName, bgName, label, options = {}] of ALL) {
  const fgHex = tokens[fgName];
  const bgHex = tokens[bgName];
  const fg = fgHex && toRgb(fgHex);
  const bg = bgHex && toRgb(bgHex);

  if (!fg || !bg) {
    rows.push(["FAIL", "—", label, `${fgName} or ${bgName} is not a colour`]);
    failures += 1;
    continue;
  }

  const value = ratio(fg, bg);
  // A shape needs 3:1 (1.4.11); large text needs 3:1 (1.4.3); everything
  // else needs 4.5:1.
  const required = options.shape || options.large ? 3.0 : 4.5;
  const passesAaa = !options.shape && value >= (options.large ? 4.5 : 7.0);

  if (value < required) {
    failures += 1;
    rows.push(["FAIL", value.toFixed(2), label, `needs ${required.toFixed(1)}`]);
  } else if (value < required + 0.6) {
    // Close enough to the line that a small future tweak would break it.
    warnings += 1;
    rows.push(["OK", value.toFixed(2), label, `only just clears ${required.toFixed(1)}`]);
  } else {
    rows.push(["OK", value.toFixed(2), label, passesAaa ? "AAA" : "AA"]);
  }
}

const width = Math.max(...rows.map(([, , label]) => label.length));
console.log("\nWCAG contrast — Roleva palette (Direction B)\n");
for (const [status, value, label, note] of rows) {
  const mark = status === "FAIL" ? "FAIL" : " OK ";
  console.log(`  ${mark}  ${value.padStart(6)}  ${label.padEnd(width)}  ${note}`);
}

console.log(
  `\n${ALL.length} checked (${PAIRS.length} text, ${SHAPES.length} shape) · ` +
    `${failures} failing · ${warnings} near the limit\n`
);

if (failures > 0) {
  console.log("Palette does not pass AA. Fix the tokens before building screens.\n");
  process.exit(1);
}
console.log("Palette passes AA.\n");
