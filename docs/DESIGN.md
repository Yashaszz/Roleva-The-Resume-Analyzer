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

## 6. Decision — and the correction

**First choice: B, The Instrument (20 Sep).** Built the primitives on it.

**Rejected on sight of the real thing, same day.** Your words: not a typical
AI-designed website. That is the reaction the trade-off table predicted — B's
row said *"Risk of looking generic: highest"* — so it was a real problem rather
than a matter of taste, and the cheapest possible moment to act was four tasks
into Phase 7 rather than thirty-two.

**Chosen direction: D — Thread.**

---

## 7. Direction D — Thread

**Concept.** The subject of this product is the **gap** between what a job
demands and what a resume shows. So the gap *is* the interface.

Demands on the left, the candidate's own sentences on the right, threads drawn
between them:

| Thread | Means |
|---|---|
| Solid | Demonstrated in a bullet |
| Dashed | Named in a skills list, never shown in use |
| **Stops at an open circle** | Nothing found at all |

The third case is why this direction exists. Every other resume tool renders a
missing requirement as a red word in a list, where it reads as one more row.
Here the absence has a *shape* — a thread that starts and goes nowhere, with
empty space beside it. The gaps are countable from across the room.

### What changed from B

| | B | D |
|---|---|---|
| Ground | Slate near-black | **Warm ink** — slate + teal *is* the generated-dashboard signature |
| Display | IBM Plex Sans, small | **Fraunces**, a high-contrast serif with an optical-size axis |
| Body | IBM Plex Sans | **Public Sans** — and specifically not Inter |
| Voice | `JOB MATCH 55.0` | *"You show two of the five things this job calls essential."* |
| Layout | Panel grid | Asymmetric, real negative space |
| Signature | A requirement matrix | **The thread map** |

Sentences instead of labels is the largest shift. B reported readings; D talks
to the person reading it.

---

## 8. Tokens

`apps/web/app/tokens.css`. Two layers, and the split is load-bearing:

- `--c-*` **primitives** — raw values. No component may reference one.
- everything else is **semantic**: `--evidence-shown`, never `--mint-400`.

**That indirection paid for itself immediately.** Switching the entire product
from B to D was a rewrite of one file plus a rename pass — the components asked
for meanings, and the meanings survived the change of direction.

---

## 9. Score-visualisation language

**No dial.** The circular progress ring is the category cliché and the least
informative rendering available for a number with five weighted components.

| Element | Treatment |
|---|---|
| Overall | 104px **Fraunces**, once per page. A statement, not a readout |
| The verdict | A display-serif *sentence*, not a band label |
| Components | Mono, with expected range beside them |
| Cap | The number turns `--status-capped` and the callout says why in words |
| Ceiling | "78 — up from 55", labelled an upper bound, not a promise |

Tabular data stays mono so columns align. The hero number is serif because it
is the page's first sentence.

---

## 10. The thread map

Covered in §7. Two things about how it is built:

**The drawing is not the information.** The SVG is `aria-hidden`, and the same
relationships sit in the DOM as a real description list — each requirement a
`<dt>`, its evidence or its absence a `<dd>`. A screen reader gets *"Docker: no
evidence found in your resume"* without touching the graphic. Threads are
progressive enhancement over a list that already works.

**Phones get the list, not the drawing.** A 132px gap between two columns of
text leaves nothing readable on either side at 375px, so below `sm` the same
data becomes stacked pairs with state on a left border. Nothing is lost but the
drawing.

---

## 11. Evidence-linking interaction model

1. **Resting state shows evidence already** — the quote sits opposite its
   requirement. Nothing hidden behind a hover.
2. **No tooltips.** Unreachable by keyboard, invisible on touch, absent from
   print. Evidence is not a hint.
3. **The quote is verbatim**, with its section and page, and has already passed
   span verification on the backend.
4. **The chain is always walkable**: score → component → requirement → quote →
   location.

---

## 12. Motion — "noticeably alive, still purposeful"

| Token | Duration | For |
|---|---|---|
| `--duration-instant` | 110ms | hover, focus, press |
| `--duration-quick` | 200ms | a panel or row arriving |
| `--duration-settle` | 420ms | a number reaching its value |
| `--duration-draw` | 900ms | one thread crossing the gap |

- **Threads draw left to right, staggered 60ms**, because that is the order the
  matching happens in. The motion explains a process rather than decorating an
  arrival. Fourteen finish in about 1.7s.
- **Decelerating easing only.** No overshoot — a score that springs past 55 and
  comes back has told the user something untrue for 200ms.
- **Nothing loops. Nothing moves on scroll.**
- `prefers-reduced-motion` zeroes every duration at the source, so a component
  written against the tokens honours it without knowing it exists. Threads still
  render — they appear rather than draw.

---

## 13. Dark / light, and verified contrast

**Dark only in v1.** Two palettes means two to verify, and a dark-first product
whose light mode is an afterthought looks worse than one with no light mode.
The semantic layer makes it a one-file change when the shared report page wants
it in Phase 8.

```
25 checked (17 text, 8 shape) · 0 failing · 0 near the limit
```

Text pairs are held to 4.5:1, shapes to 3:1 (WCAG 1.4.11 — a thread is a
graphical object required to understand content).

### What the checker caught, in both palettes

It has now found the same class of mistake twice, which is the argument for
running it before screens exist rather than after.

**In B:** a listed-only fill dark enough to hold light text measured 2.57:1
against its own panel — readable label, invisible cell. And `--line-strong`, a
hairline whose entire purpose is to be seen, measured **1.50:1**.

**In D:** three colours picked by eye from the mockup failed —

| Token | Measured | Now |
|---|---|---|
| The listed-only thread | **2.95** | 5.45 |
| The absent border | **2.62** | 3.97 |
| The meaningful hairline | **1.40** | 3.61 |

A thread that cannot be seen is not a subtle thread. It is a missing one — and
in this direction the thread *is* the information.

### Greyscale

Colour does **not** carry the distinction between the two unfilled states: in
greyscale they land within six points of each other. The mark (●/◐/○) and the
line style (solid / dashed / stopped) are what actually carry it. That is why
the rule is "never colour alone" rather than "pick distinguishable colours".
