/**
 * The thread map — this direction's signature, and the one component that has
 * to be right.
 *
 * What a job demands sits on the left. What the resume actually says sits on the
 * right. A thread runs between them when evidence was found:
 *
 *   solid   — demonstrated in a bullet
 *   dashed  — named in a skills list, never shown in use
 *   stopped — a short stub ending in an open circle: nothing was found at all
 *
 * The third case is the reason this design exists. Every other resume tool
 * renders a missing requirement as a red word in a list, where it reads as one
 * more row. Here the absence has a shape: a thread that starts and goes nowhere,
 * with empty space beside it. You can count the gaps from across the room.
 *
 * ACCESSIBILITY — the drawing is not the information.
 *
 * The SVG is `aria-hidden`, and the same relationships are in the DOM as a real
 * description list: each requirement is a `<dt>`, its evidence (or its absence)
 * is a `<dd>`. A screen reader gets "Docker: no evidence found in your resume"
 * without ever touching the graphic. The threads are progressive enhancement
 * over a list that works on its own.
 */
"use client";

import { useEffect, useRef, useState } from "react";

export type ThreadState = "shown" | "listed" | "absent";

export type ThreadRow = {
  id: string;
  /** The requirement, as the posting words it. */
  requirement: string;
  priority: "must" | "strong" | "nice";
  state: ThreadState;
  /** The resume line that satisfies it. Absent rows have none. */
  evidence?: string;
  /** Where that line was found, e.g. "Experience, page 1". */
  location?: string;
};

const STROKE: Record<ThreadState, string> = {
  shown: "var(--thread-shown)",
  listed: "var(--thread-listed)",
  absent: "var(--thread-absent)",
};

const ROW_HEIGHT = 44;
const GAP_WIDTH = 132;

export function ThreadMap({ rows }: { rows: ThreadRow[] }) {
  const height = rows.length * ROW_HEIGHT;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-4">
        <span className="label">What the job asks → what your resume shows</span>
        <ThreadLegend />
      </div>

      <div className="bg-panel border border-line-subtle rounded-md p-5 sm:p-6">
        {/*
         * One grid, three columns, so a row's requirement, its thread and its
         * evidence always share a baseline. The middle column collapses on a
         * phone — see the stacked layout below.
         */}
        <dl className="hidden sm:grid gap-0 m-0" style={{ gridTemplateColumns: `minmax(180px, 250px) ${GAP_WIDTH}px 1fr` }}>
          {/* Column 1 — the demands */}
          <div className="flex flex-col">
            {rows.map((row) => (
              <dt
                key={row.id}
                className="flex items-center gap-3 m-0"
                style={{ height: ROW_HEIGHT }}
              >
                <span
                  className={`font-mono text-2xs tracking-[var(--tracking-label)] w-[46px] shrink-0 ${
                    row.state === "absent" ? "text-absent" : "text-muted"
                  }`}
                >
                  {row.priority}
                </span>
                <span
                  className={`text-md font-semibold truncate ${
                    row.state === "absent" ? "text-absent" : "text-primary"
                  }`}
                >
                  {row.requirement}
                </span>
              </dt>
            ))}
          </div>

          {/* Column 2 — the threads. Decorative: the relationships are in the
              dt/dd pairing either side of it. */}
          <div aria-hidden="true">
            <ThreadCanvas rows={rows} height={height} />
          </div>

          {/* Column 3 — the evidence */}
          <div className="flex flex-col">
            {rows.map((row) => (
              <dd key={row.id} className="flex items-center m-0" style={{ height: ROW_HEIGHT }}>
                <EvidenceLine row={row} />
              </dd>
            ))}
          </div>
        </dl>

        {/*
         * Phone layout. The threads cannot survive a 375px screen — a 132px gap
         * between two columns of text leaves nothing readable on either side —
         * so below `sm` the same data becomes stacked pairs with the state on a
         * left border. Nothing is lost except the drawing, which was never
         * where the information lived.
         */}
        <dl className="sm:hidden flex flex-col gap-4 m-0">
          {rows.map((row) => (
            <div key={row.id} className="flex flex-col gap-1.5">
              <dt className="flex items-center gap-2 m-0">
                <span
                  className={`font-mono text-2xs tracking-[var(--tracking-label)] ${
                    row.state === "absent" ? "text-absent" : "text-muted"
                  }`}
                >
                  {row.priority}
                </span>
                <span
                  className={`text-md font-semibold ${
                    row.state === "absent" ? "text-absent" : "text-primary"
                  }`}
                >
                  {row.requirement}
                </span>
              </dt>
              <dd className="m-0">
                <EvidenceLine row={row} />
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}

/**
 * The drawing.
 *
 * Threads draw one after another, left to right, because that is the order the
 * matching happens in — the motion explains a process rather than decorating an
 * arrival. Under `prefers-reduced-motion` the duration token is 0ms and every
 * thread is simply present, which loses the choreography and keeps all of the
 * information.
 */
function ThreadCanvas({ rows, height }: { rows: ThreadRow[]; height: number }) {
  const [drawn, setDrawn] = useState(false);
  const ref = useRef<SVGSVGElement>(null);

  useEffect(() => {
    // One frame's delay so the dash offset is applied before it animates;
    // setting both in the same paint produces no transition at all.
    const id = requestAnimationFrame(() => setDrawn(true));
    return () => cancelAnimationFrame(id);
  }, []);

  return (
    <svg
      ref={ref}
      width={GAP_WIDTH}
      height={height}
      viewBox={`0 0 ${GAP_WIDTH} ${height}`}
      fill="none"
      aria-hidden="true"
      className="block"
    >
      {rows.map((row, index) => {
        const y = index * ROW_HEIGHT + ROW_HEIGHT / 2;
        const stroke = STROKE[row.state];
        const delay = `calc(${index} * var(--stagger-step))`;

        if (row.state === "absent") {
          // A stub that stops short, then an open circle. The gap after it is
          // deliberate: that emptiness is the finding.
          return (
            <g key={row.id}>
              <line
                x1="0"
                y1={y}
                x2="44"
                y2={y}
                stroke={stroke}
                strokeWidth="var(--thread-width)"
                style={{
                  opacity: drawn ? 1 : 0,
                  transition: `opacity var(--duration-quick) var(--ease-out) ${delay}`,
                }}
              />
              <circle
                cx="52"
                cy={y}
                r="4.5"
                stroke={stroke}
                strokeWidth="1.4"
                fill="none"
                style={{
                  opacity: drawn ? 1 : 0,
                  transition: `opacity var(--duration-quick) var(--ease-out) ${delay}`,
                }}
              />
            </g>
          );
        }

        // A curve rather than a straight line: threads cross, and a curve makes
        // two crossing paths readable where two straight lines become an X.
        const path = `M0 ${y} C ${GAP_WIDTH * 0.45} ${y}, ${GAP_WIDTH * 0.55} ${y}, ${GAP_WIDTH} ${y}`;
        const length = GAP_WIDTH;

        return (
          <path
            key={row.id}
            d={path}
            stroke={stroke}
            strokeWidth="var(--thread-width)"
            strokeDasharray={row.state === "listed" ? "4 4" : length}
            style={
              row.state === "listed"
                ? {
                    opacity: drawn ? 0.9 : 0,
                    transition: `opacity var(--duration-quick) var(--ease-out) ${delay}`,
                  }
                : {
                    strokeDashoffset: drawn ? 0 : length,
                    transition: `stroke-dashoffset var(--duration-draw) var(--ease-out) ${delay}`,
                  }
            }
          />
        );
      })}
    </svg>
  );
}

function EvidenceLine({ row }: { row: ThreadRow }) {
  if (row.state === "absent") {
    return (
      <span className="flex items-center h-full w-full px-3 py-1.5 rounded-sm border border-dashed border-line-strong text-sm text-muted italic">
        Nothing in your resume to connect this to
      </span>
    );
  }

  if (row.state === "listed") {
    return (
      <span className="flex items-center h-full w-full px-3 py-1.5 rounded-r-sm border-l-2 border-dashed border-listed-line bg-panel text-sm text-secondary">
        Skills row only — <em className="italic">&nbsp;never shown in use</em>
      </span>
    );
  }

  return (
    <span className="flex flex-col justify-center h-full w-full px-3 py-1.5 rounded-r-sm border-l-2 border-solid border-shown-line bg-shown-bg">
      <span className="text-sm text-primary leading-snug truncate">“{row.evidence}”</span>
      {row.location ? (
        <span className="font-mono text-2xs text-muted tracking-[var(--tracking-label)]">
          {row.location}
        </span>
      ) : null}
    </span>
  );
}

function ThreadLegend() {
  const items: { state: ThreadState; text: string }[] = [
    { state: "shown", text: "Demonstrated" },
    { state: "listed", text: "Listed only" },
    { state: "absent", text: "Nothing found" },
  ];

  return (
    <ul className="hidden md:flex gap-4 m-0 p-0 list-none">
      {items.map(({ state, text }) => (
        <li key={state} className="flex items-center gap-1.5">
          <svg width="22" height="8" aria-hidden="true" className="block">
            {state === "absent" ? (
              <>
                <line x1="0" y1="4" x2="10" y2="4" stroke={STROKE[state]} strokeWidth="1.6" />
                <circle cx="15" cy="4" r="3" stroke={STROKE[state]} strokeWidth="1.3" fill="none" />
              </>
            ) : (
              <line
                x1="0"
                y1="4"
                x2="22"
                y2="4"
                stroke={STROKE[state]}
                strokeWidth="1.6"
                strokeDasharray={state === "listed" ? "3 3" : undefined}
              />
            )}
          </svg>
          <span className="font-mono text-2xs tracking-[var(--tracking-label)] uppercase text-muted">
            {text}
          </span>
        </li>
      ))}
    </ul>
  );
}
