# Roleva — Design Exploration

Phase 6. Three directions, one decision.

Canvas: <https://claude.ai/artifact/TkANYkWaaLZNnDNrxo5KRu> (private until shared)

---

## 1. Reference research — what to avoid

### The shape we are not building

The brief ruled this out explicitly, and it is worth writing down so it cannot
creep back in one component at a time:

> Navbar → hero section → gradient background → feature cards → testimonials →
> pricing → footer

Every resume tool currently shipping uses some version of it. The reason is not
that it works; it is that it is the path of least resistance, and it signals
"generic SaaS" before a single word is read.

### Specific tropes excluded

| Trope | Why it is out |
|---|---|
| Gradient washes, glow, glassmorphism | Decoration that carries no information. On a page whose claim is "every number is traceable", ornament actively undermines the argument. |
| Inter / Roboto / Arial | Not bad typefaces — but they are the default of everything AI-generated in 2024–26. Recognisable as *absence of a choice*. |
| Left-border cards stacked in a column | The single most common LLM-generated layout. |
| Emoji as iconography | Reads as unserious on a page telling someone their application is weak. |
| A big animated circular score dial | Every competitor has one. It is also the least informative possible rendering of a number that has five components. |
| Confetti / celebration on results | The result is frequently bad news. |

### What we are aiming at instead

Three reference worlds, one per direction:

- **A** — audit reports, financial statements, legal exhibits. Documents whose
  entire credibility rests on traceability.
- **B** — measuring instruments: audio mastering meters, oscilloscopes, flight
  displays. Dense, calibrated, no decoration, information at a glance.
- **C** — manuscript annotation: an editor's margin notes, a supervisor's
  comments on a draft. Criticism attached to the exact line it concerns.

### The constraint that shapes all three

Roleva's core claim is that **every number traces to a line in the user's own
resume**. A design that shows scores and hides evidence contradicts the product
at the level of layout. In each direction, evidence is visible without a click —
not behind a tooltip, an accordion or a hover.

---

## 2. Direction A — The Ledger

**Concept.** The report is an audit record. Not a dashboard, not a scorecard — a
document you could print and hand to someone.

| Aspect | Decision |
|---|---|
| Typography | Newsreader (transitional serif) for prose and headings; IBM Plex Mono for every figure |
| Colour | Warm paper `#FBFAF7`, ink `#17150F`, single red `#A3241C` used *only* for deficits |
| Layout | Ruled rows. No cards, no shadows, no rounded corners. Hairline rules do the separating |
| Motion | Almost none. Numbers set once; rules draw in on first paint. No scroll-triggered anything |
| Evidence | Quoted in italic on the same row as the requirement it supports, with its section and page |

**Strength.** The layout *is* the product claim: a number, then its source,
on one line. Highest credibility per pixel of the three, and the cheapest to
build well.

**Cost.** Austere. A first-year student who has just been told they score 55 may
read this as a verdict rather than as help. Risks feeling like a rejection letter.

---

## 3. Direction B — The Instrument

**Concept.** A measuring device rather than a document. Dark ground so that data
is the only thing emitting light.

| Aspect | Decision |
|---|---|
| Typography | IBM Plex Sans + IBM Plex Mono. One family, two voices |
| Colour | Near-black `#0B0E0F`; teal `#7FE3D0` = demonstrated; amber `#F2B155` = capped or partial; red-brown `#3A2222` = absent. Colour is data, never decoration |
| Layout | Panels on a strict grid. The requirement matrix is the hero — all 14 requirements readable in one glance |
| Motion | Values settle rather than animate. Grid cells fade in staggered by 12ms, once |
| Evidence | The matrix cell carries strength; the panel beneath carries the quote |

**Strength.** The requirement map genuinely needs density, and this is the only
direction that gives it room. Dark also removes some of the exam-paper anxiety of
a white page delivering bad news.

**Cost.** Closest of the three to familiar developer tooling. Needs real
restraint to avoid reading as a dashboard template — which is the exact failure
mode the brief forbids.

---

## 4. Direction C — The Margin

**Concept.** Your resume *is* the interface. The document sits at reading size on
the left with evidence highlighted in place; the analysis lives in the margin
beside it, the way a supervisor annotates a draft.

| Aspect | Decision |
|---|---|
| Typography | Instrument Serif for display; Libre Franklin for body; IBM Plex Mono for figures |
| Colour | Paper `#EFEBE2`, document white, annotation green `#2E7D4F` = evidence found, amber `#B45309` = needs work, ink blue `#1F4B7A` for links |
| Layout | Two columns: document, margin. The score is a small persistent object in the bar — never a hero number |
| Motion | Annotations settle into the margin; highlighting a note dims the rest of the document |
| Evidence | Literal. The highlight *is* the evidence; the note points at it |

**Strength.** Makes evidence-linking structural rather than an interaction. The
least like anything else in this category, and it directly answers "where was the
evidence found" without the user asking.

**Cost.** By far the most work. Requires faithfully reflowing extracted text into
a readable document view, and the span offsets have to survive into the DOM.
Mobile needs a genuine rethink — a stacked column loses the whole idea.

---

## 5. Trade-offs, side by side

| | A — Ledger | B — Instrument | C — Margin |
|---|---|---|---|
| Credibility | **Highest** | High | High |
| Originality in category | Medium | Low–medium | **Highest** |
| Evidence made visible | On every row | In a panel | **Structurally** |
| Density | Medium | **Highest** | Medium |
| Tone toward a struggling user | Cold | Neutral | **Warmest** |
| Build cost (Phase 7) | **Lowest** | Medium | Highest |
| Mobile | Straightforward | Hard (density) | **Needs redesign** |
| Risk of looking generic | Low | **Highest** | Lowest |

### My recommendation

**C — The Margin**, with A's typographic discipline applied to it.

It is the only one where the layout makes the product's central claim *without
explaining it*. A user sees their own sentence highlighted, with the reason
beside it, and understands the whole idea in about two seconds. A and B both
require them to trust that the quote came from where we say it did.

The cost is real and I would rather state it plainly: C is roughly twice the
frontend work of A, and its mobile layout is a separate design problem rather
than a responsive adjustment of the desktop one.

**If build time matters more than distinctiveness, choose A.** It is honest,
fast, and nothing about it is embarrassing.

---

## 6. Decision

> **Chosen direction: B — The Instrument.** Chosen 20 Sep 2026.

Everything below follows from that choice.

---

## 7. Tokens

`apps/web/app/tokens.css`. Two layers, and the split is load-bearing:

- `--c-*` **primitives** — raw values. No component may reference one.
- everything else is **semantic**. A component asks for `--evidence-shown`,
  never `--teal-300`.

That indirection is why a light theme is possible later without touching a
component, and why "which teal was the matched one" is never a question anyone
has to answer.

**The rule for the rest of the codebase:** no raw hex, no magic pixel values, no
inline transition timings. A missing value means a missing token.

---

## 8. Score-visualisation language

**No dial.** The circular progress ring is the category cliché and it is also
the least informative rendering available for a number with five weighted
components.

| Element | Treatment |
|---|---|
| Overall | 78px mono numeral, once per page. Set in mono so it does not change width as it settles |
| Components | 34px mono, three across, each with its expected range beside it |
| Cap | When the must-have gate fires, the overall number turns `--status-capped` and the word CAPPED sits beside it. The cap is the most important fact on the page when it applies |
| Expected range | Always labelled "typical", never a percentile. Percentiles appear only above N=30 |
| Ceiling | "78 — six changes away" — the projected total from the advice engine, shown beside the current score |

Every number on the page is monospaced. A score that reflows while it counts
looks unstable, and this product's whole argument is that its numbers are solid.

---

## 9. Requirement map

The hero of this direction. Fourteen requirements legible in one glance, as a
7-column grid of cells.

**Three states, and state is never carried by colour alone:**

| State | Rendering | Mark |
|---|---|---|
| Demonstrated | Filled `--evidence-shown-bg`, dark label | ● filled |
| Listed only | Panel background, `--evidence-listed-line` outline | ◐ half |
| Absent | Recessed `--evidence-absent-bg`, `--evidence-absent-line` outline | ○ empty |

The mark is an inline SVG, not a character, so it renders identically
everywhere. The cell also carries the priority (MUST / STRONG / NICE) and the
requirement name as text.

**Measured, not assumed.** Converting the palette to greyscale puts the two
outlined states at 54 and 48 out of 255 — effectively identical. So the colours
do *not* carry this distinction on a monochrome printout; the mark and the
border style do:

| State | Fill (greyscale) | Border | Mark |
|---|---|---|---|
| Demonstrated | 163 — unmistakable | none | ● filled |
| Listed only | 2 | solid | ◐ half |
| Absent | 3 | **dashed** | ○ empty |

That is the point of the rule. Had the marks been decoration rather than the
actual carrier, this design would have failed on the first printed copy and
nobody would have found out until a user mentioned it.

### A conflict the contrast check surfaced

The first palette filled all three states. A mid-teal dark enough to hold light
text measured **2.57:1 against its own panel** — meaning the cell's shape was
invisible even though its label was readable.

Making *demonstrated* the only filled state resolves it, and says something
true: evidence is the presence of something, and the other two states are
degrees of its absence.

---

## 10. Evidence-linking interaction model

The product's central claim is that every number traces to a line in the user's
own résumé. The interaction has to make that **cheap to check**, not merely
possible.

1. **Resting state shows evidence already.** The panel under the map carries the
   quote for whichever requirement is focused. Nothing is hidden behind a hover.
2. **Selecting a cell** swaps the quote panel and marks the cell. Click or
   keyboard; the cells are real `<button>`s in a grid with arrow-key movement.
3. **The quote is verbatim**, with its section and page. It has already passed
   span verification on the backend — anything that failed was dropped and never
   reaches the client.
4. **No tooltips.** A tooltip is unreachable by keyboard, invisible on touch,
   and unprintable. Evidence is not a hint.
5. **The chain is always walkable**: score → component → requirement → quote →
   location. Four steps, no dead ends.

---

## 11. Motion

Values **settle**; they do not perform.

| Token | Duration | Used for |
|---|---|---|
| `--duration-instant` | 90ms | hover, focus, press |
| `--duration-quick` | 160ms | a panel appearing |
| `--duration-settle` | 320ms | a number arriving at its value |

- **Easing is decelerating only** — `cubic-bezier(0.2, 0, 0, 1)`. No spring, no
  overshoot. A score that springs past 55 and comes back has told the user
  something untrue for 200ms.
- **Stagger is 12ms**, so fourteen grid cells finish in under 200ms.
- **Nothing loops.** The only continuous motion in the product is the progress
  indicator during analysis, which represents real stage transitions.
- **Nothing animates on scroll.** Scroll-triggered reveals make a report feel
  like a marketing page.
- `prefers-reduced-motion` zeroes every duration token at the source, so a
  component written against the tokens honours it without knowing it exists.

An analysis takes thirty seconds and the user is already anxious. Animation that
draws attention to itself makes the wait worse.

---

## 12. Dark / light

**Dark only in v1.** The decision, with its reasoning:

- Two palettes means two palettes to verify for contrast, and a dark-first
  product whose light mode is an afterthought looks worse than one with no light
  mode at all.
- The semantic token layer exists so light is a later change to one file.
- The case most likely to want it is the **shared report page** — a recruiter
  opening a link on a bright screen — and that is Phase 8.

### Contrast, verified

`scripts/check-contrast.mjs` reads the real token file, resolves `var()` chains,
and checks every pair the design uses:

```
26 checked (19 text, 7 shape) · 0 failing · 0 near the limit
```

Text pairs are held to 4.5:1 (AA), shapes to 3:1 (WCAG 1.4.11 — a cell's fill is
a graphical object required to understand content). Anything clearing by less
than 0.6 is reported as near the limit, because a palette that *just* passes is
one small tweak from failing.

**The list in that script is the contract.** A combination not in it is a
combination nobody has verified.

It caught two real problems before a single screen existed: the filled-state
conflict above, and `--line-strong` — a hairline explicitly meant to be seen —
measuring **1.50:1**, which is a line nobody could see.
