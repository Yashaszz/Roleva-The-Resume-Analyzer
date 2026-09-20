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

> **Chosen direction:** _pending_
>
> Recorded here once you choose. Gate 6 does not pass until this line names one.

---

## 7. Still to do in Phase 6 (after the choice)

- 6.7 Design token system — colour, type, space, radius, motion
- 6.8 Score-visualisation language, custom SVG
- 6.9 Requirement-map visualisation
- 6.10 Evidence-linking interaction model
- 6.11 Motion system — durations, easings, choreography
- 6.12 Dark/light decision and locked palette, AA contrast verified before any screen is built
