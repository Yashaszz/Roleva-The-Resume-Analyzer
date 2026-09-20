/**
 * The skill ledger and the evidence viewer. 7.22 and 7.23.
 *
 * Must-haves are separated from the rest and listed first, because they are the
 * only ones that decide whether an application survives a screen. Burying a
 * missing essential requirement among twelve nice-to-haves is how a resume tool
 * gives technically complete advice that is useless.
 *
 * **The evidence viewer is the product.** Clicking any requirement shows the
 * exact line from the resume that satisfied it, verbatim, with where it was
 * found. Those quotes have already passed span verification on the server —
 * anything whose recorded offsets did not match the source text was dropped and
 * never reaches here. So a quote on this page is not a claim about the resume;
 * it *is* the resume.
 */
"use client";

import { useState } from "react";

import { EvidenceMark, Panel, PanelTitle } from "@/components/ui/Panel";
import type { AnalysisReport, Priority } from "@/lib/types";

/*
 * Prop types are derived from the report rather than from the standalone
 * aliases. The generated schemas inline their nested objects, so
 * `RequirementMatch` and `report.matches.matches[number]` are same-named but
 * structurally distinct as far as TypeScript is concerned — and several of the
 * arrays are optional, because Pydantic's default_factory fields are not
 * required in the JSON schema. Taking the types from the thing we are actually
 * handed removes both problems.
 */
type Requirement = NonNullable<AnalysisReport["job"]["requirements"]>[number];
type RequirementMatch = NonNullable<AnalysisReport["matches"]["matches"]>[number];

type Row = {
  requirement: Requirement;
  key: string;
  match: RequirementMatch | null;
};

export function SkillLedger({
  requirements,
  matches,
}: {
  requirements: Requirement[];
  matches: RequirementMatch[];
}) {
  const byId = new Map(matches.map((match) => [match.requirement_id, match]));
  // `id` is optional in the generated schema because the API fills it from a
  // default_factory. It is always present in practice; falling back to the text
  // keeps the lookup total rather than asserting it away.
  const rows: Row[] = requirements.map((requirement) => ({
    requirement,
    key: requirement.id ?? requirement.text,
    match: byId.get(requirement.id ?? "") ?? null,
  }));

  const essential = rows.filter((row) => row.requirement.priority === "must");
  const rest = rows.filter((row) => row.requirement.priority !== "must");

  return (
    <section className="flex flex-col gap-6">
      <Group
        title="Essential requirements"
        note="These decide whether your application gets read at all."
        rows={essential}
      />
      {rest.length > 0 ? (
        <Group title="Everything else the posting asks for" rows={rest} />
      ) : null}
    </section>
  );
}

function Group({ title, note, rows }: { title: string; note?: string; rows: Row[] }) {
  if (rows.length === 0) return null;

  const met = rows.filter((row) => (row.match?.strength ?? 0) >= 0.5).length;

  return (
    <div className="flex flex-col gap-3">
      <PanelTitle
        right={
          <span className="numeric text-sm text-muted">
            {met}/{rows.length}
          </span>
        }
      >
        {title}
      </PanelTitle>
      {note ? <p className="text-sm text-muted m-0 -mt-2">{note}</p> : null}

      <Panel padded={false}>
        <ul className="flex flex-col m-0 p-0 list-none">
          {rows.map((row) => (
            <LedgerRow key={row.key} row={row} />
          ))}
        </ul>
      </Panel>
    </div>
  );
}

function LedgerRow({ row }: { row: Row }) {
  const [open, setOpen] = useState(false);
  const state = stateOf(row.match);
  const evidence = row.match?.evidence ?? [];
  const canOpen = evidence.length > 0 || Boolean(row.match?.explanation);

  const tone = {
    shown: "text-shown",
    listed: "text-primary",
    absent: "text-absent",
  }[state];

  return (
    <li className="border-b border-line-subtle last:border-b-0">
      {/*
       * A real button when there is something to reveal, a plain row when there
       * is not. A disabled-looking button that does nothing on click is worse
       * than no button — the user assumes it is broken rather than empty.
       */}
      {canOpen ? (
        <button
          type="button"
          onClick={() => setOpen((current) => !current)}
          aria-expanded={open}
          className="w-full flex items-center gap-3 px-5 py-3 min-h-[52px] text-left bg-transparent border-0 cursor-pointer hover:bg-raised transition-colors [transition-duration:var(--duration-instant)]"
        >
          <RowBody row={row} state={state} tone={tone} />
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            aria-hidden="true"
            className={`shrink-0 text-muted transition-transform [transition-duration:var(--duration-instant)] ${open ? "rotate-90" : ""}`}
          >
            <path d="m9 6 6 6-6 6" />
          </svg>
        </button>
      ) : (
        <div className="w-full flex items-center gap-3 px-5 py-3 min-h-[52px]">
          <RowBody row={row} state={state} tone={tone} />
        </div>
      )}

      {open ? (
        <div className="px-5 pb-4 pl-[46px] flex flex-col gap-3">
          {evidence.map((item, index) => (
            <figure key={index} className="m-0 flex flex-col gap-1">
              <blockquote className="m-0 pl-3 border-l-2 border-shown-line bg-shown-bg py-2 pr-3 rounded-r-sm">
                <p className="text-base text-primary leading-normal m-0">
                  “{item.span.text}”
                </p>
              </blockquote>
              <figcaption className="label">
                {originLabel(item.origin)}
                {item.span.page ? ` · page ${item.span.page}` : ""}
                {item.similarity != null ? ` · ${Math.round(item.similarity * 100)}% match` : ""}
              </figcaption>
            </figure>
          ))}

          {row.match?.explanation ? (
            <p className="text-sm text-secondary leading-normal m-0">
              {row.match.explanation}
            </p>
          ) : null}

          {evidence.length === 0 && !row.match?.explanation ? (
            <p className="text-sm text-muted m-0">
              Nothing in your resume matched this.
            </p>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function RowBody({
  row,
  state,
  tone,
}: {
  row: Row;
  state: "shown" | "listed" | "absent";
  tone: string;
}) {
  return (
    <>
      <span className={`flex items-center shrink-0 ${tone}`}>
        <EvidenceMark state={state} />
      </span>

      <span className="flex-1 min-w-0 flex flex-col gap-0.5">
        <span className={`text-base ${state === "absent" ? "text-absent" : "text-primary"}`}>
          {row.requirement.text}
        </span>
        <span className="label">
          {priorityLabel(row.requirement.priority)} · {stateLabel(state)}
        </span>
      </span>

      <span className={`numeric text-sm shrink-0 ${tone}`}>
        {(row.match?.strength ?? 0).toFixed(2)}
      </span>
    </>
  );
}

function stateOf(match: RequirementMatch | null): "shown" | "listed" | "absent" {
  if (!match || match.status === "missing" || match.strength === 0) return "absent";
  // Half credit is what a skills-list mention earns, by design: the origin
  // weighting is the product's signature finding.
  if (match.status === "partial" || match.strength <= 0.5) return "listed";
  return "shown";
}

const STATES = {
  shown: "Demonstrated in a bullet",
  listed: "Listed, not demonstrated",
  absent: "No evidence found",
};

function stateLabel(state: keyof typeof STATES): string {
  return STATES[state];
}

const PRIORITIES: Record<Priority, string> = {
  must: "Essential",
  strong: "Strongly wanted",
  nice: "Nice to have",
};

function priorityLabel(priority: Priority): string {
  return PRIORITIES[priority] ?? priority;
}

const ORIGINS: Record<string, string> = {
  experience_bullet: "Experience",
  project_bullet: "Projects",
  certification: "Certifications",
  summary: "Summary",
  skills_list: "Skills list",
  education: "Education",
  other: "Elsewhere",
};

function originLabel(origin: string): string {
  return ORIGINS[origin] ?? origin;
}
