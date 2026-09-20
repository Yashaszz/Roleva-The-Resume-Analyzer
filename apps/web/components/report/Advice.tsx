/**
 * Recommendations, ATS findings and bullet rewrites. 7.24, 7.26, 7.27.
 *
 * Recommendations are ranked by **measured** projected gain — the scoring engine
 * re-run on a modified copy of its own inputs, not a model's estimate. That is
 * why each one can carry a number, and why the number is worth showing.
 *
 * The "up to" on the total is not hedging. Each projection is measured against
 * the same baseline, so two fixes that lift the same cap do not add up. Saying
 * "+24 points" would be arithmetic the product cannot honour.
 */
"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Panel, PanelTitle } from "@/components/ui/Panel";
import { useToast } from "@/components/ui/Toast";
import type { AnalysisReport } from "@/lib/types";

type Recommendation = NonNullable<AnalysisReport["recommendations"]>[number];
type BulletSuggestion = NonNullable<AnalysisReport["bullet_suggestions"]>[number];
type AtsFinding = NonNullable<AnalysisReport["ats"]["findings"]>[number];
type SectionFeedbackItem = NonNullable<AnalysisReport["section_feedback"]>[number];

export function Recommendations({ items }: { items: Recommendation[] }) {
  if (items.length === 0) {
    return (
      <section className="flex flex-col gap-3">
        <PanelTitle>What to fix</PanelTitle>
        <Panel>
          <p className="text-base text-secondary m-0">
            Nothing worth changing for this posting. That is a real result, not an empty
            state — every check Roleva runs came back clean.
          </p>
        </Panel>
      </section>
    );
  }

  const total = items.reduce((sum, item) => sum + item.projected_gain, 0);

  return (
    <section className="flex flex-col gap-4">
      <PanelTitle
        right={
          total > 0 ? (
            <span className="text-sm text-muted">
              up to <span className="numeric text-shown">+{total.toFixed(1)}</span> points
            </span>
          ) : null
        }
      >
        Worth doing first
      </PanelTitle>

      <ol className="flex flex-col m-0 p-0 list-none">
        {items.map((item) => (
          <li
            key={item.id}
            className="flex gap-4 sm:gap-5 py-4 border-b border-line-subtle last:border-b-0"
          >
            <span
              className={`display shrink-0 w-[68px] ${
                item.projected_gain > 0 ? "text-shown" : "text-muted"
              }`}
              style={{ fontSize: "var(--text-lg)" }}
            >
              {item.projected_gain > 0 ? `+${item.projected_gain.toFixed(1)}` : "+0"}
            </span>

            <div className="flex-1 min-w-0 flex flex-col gap-1.5">
              <h3 className="text-base font-semibold text-primary m-0">{item.title}</h3>
              <p className="text-base text-secondary leading-normal m-0">{item.detail}</p>
            </div>
          </li>
        ))}
      </ol>

      {total > 0 ? (
        <p className="text-sm text-muted leading-normal max-w-[68ch]">
          An upper bound, not a promise. Each gain is measured against your current
          score, so two fixes that lift the same cap do not add together.
        </p>
      ) : null}
    </section>
  );
}

/**
 * ATS findings. 7.24.
 *
 * Every finding says what was found, where, what it costs and how to fix it.
 * The API's rule registry produces all four, so a finding that cannot answer
 * "how do I fix this" does not exist.
 */
export function AtsChecklist({
  findings,
  checksRun,
  hiddenText,
}: {
  findings: AtsFinding[];
  checksRun: number;
  hiddenText: boolean;
}) {
  return (
    <section className="flex flex-col gap-4">
      <PanelTitle right={<span className="label">{checksRun} checks run</span>}>
        How machines will read this
      </PanelTitle>

      {hiddenText ? (
        <div className="flex gap-3 p-4 bg-absent-bg border-l-2 border-absent-line rounded-r-sm">
          <p className="text-base text-secondary leading-normal m-0">
            <strong className="text-absent">This document contains hidden text.</strong>{" "}
            White-on-white or zero-size text is treated as keyword stuffing by most
            applicant tracking systems, and by most recruiters who notice it. Roleva
            stripped it before analysing, so it earned you nothing here either.
          </p>
        </div>
      ) : null}

      {findings.length === 0 ? (
        <Panel>
          <p className="text-base text-secondary m-0">
            Nothing to fix. Your resume parses cleanly, so nothing is lost before a
            human reads it.
          </p>
        </Panel>
      ) : (
        <Panel padded={false}>
          <ul className="flex flex-col m-0 p-0 list-none">
            {findings.map((finding, index) => (
              <li
                key={`${finding.rule_id}-${index}`}
                className="flex gap-4 px-5 py-4 border-b border-line-subtle last:border-b-0"
              >
                <span
                  className={`numeric text-sm shrink-0 w-[46px] text-right ${
                    finding.severity === "critical" || finding.severity === "major"
                      ? "text-absent"
                      : "text-capped"
                  }`}
                >
                  −{finding.deduction.toFixed(0)}
                </span>
                <div className="flex-1 min-w-0 flex flex-col gap-1.5">
                  <h3 className="text-base font-semibold text-primary m-0">
                    {finding.title}
                    {finding.page ? (
                      <span className="label ml-2">page {finding.page}</span>
                    ) : null}
                    {finding.occurrences > 1 ? (
                      <span className="label ml-2">×{finding.occurrences}</span>
                    ) : null}
                  </h3>
                  <p className="text-sm text-secondary leading-normal m-0">
                    {finding.detail}
                  </p>
                  <p className="text-sm text-shown leading-normal m-0">{finding.fix}</p>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </section>
  );
}

/**
 * Suggested rewrites. 7.26.
 *
 * Every suggestion here passed the grounding validator: it introduces no
 * number, technology, employer or product that the original did not already
 * contain. Ones that failed twice were dropped rather than shown, so this list
 * being shorter than expected is the safety working.
 *
 * The original is kept visible beside the rewrite. A user has to be able to see
 * what changed to decide whether they agree with it — and it is their resume,
 * so agreeing is the point.
 */
export function BulletSuggestions({ suggestions }: { suggestions: BulletSuggestion[] }) {
  if (suggestions.length === 0) return null;

  return (
    <section className="flex flex-col gap-4">
      <PanelTitle>Lines worth rewriting</PanelTitle>
      <div className="flex flex-col gap-4">
        {suggestions.map((suggestion) => (
          <SuggestionCard key={suggestion.bullet_id} suggestion={suggestion} />
        ))}
      </div>
      <p className="text-sm text-muted leading-normal max-w-[68ch]">
        None of these add a fact your resume did not already contain — no invented
        numbers, tools or employers. Suggestions that tried were dropped.
      </p>
    </section>
  );
}

function SuggestionCard({ suggestion }: { suggestion: BulletSuggestion }) {
  const toast = useToast();
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(suggestion.suggestion);
      setCopied(true);
      toast("Copied to clipboard", "good");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be refused — an insecure origin, a permissions
      // policy, an older browser. The text is on screen and selectable either
      // way, so this is a failed convenience rather than a failed action.
      toast("Couldn't copy — select the text and copy it manually");
    }
  }

  return (
    <Panel className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <span className="label">Your line</span>
        <p className="text-base text-muted leading-normal m-0">{suggestion.original}</p>
      </div>

      <svg
        width="15"
        height="15"
        viewBox="0 0 24 24"
        fill="none"
        stroke="var(--evidence-shown)"
        strokeWidth="1.8"
        aria-hidden="true"
      >
        <path d="M12 5v14M6 13l6 6 6-6" />
      </svg>

      <div className="flex flex-col gap-1">
        <span className="label">Stronger</span>
        <p className="text-base text-primary leading-normal m-0">{suggestion.suggestion}</p>
      </div>

      {(suggestion.reasons ?? []).length > 0 ? (
        <ul className="flex flex-col gap-1 m-0 p-0 list-none">
          {(suggestion.reasons ?? []).map((reason, index) => (
            <li key={index} className="text-sm text-muted">
              {reason}
            </li>
          ))}
        </ul>
      ) : null}

      <div className="flex justify-end">
        <Button variant="secondary" size="sm" onClick={copy}>
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
    </Panel>
  );
}

/**
 * Section-by-section feedback. 7.25.
 *
 * Rated 1–5 against the same anchored rubric the quality score uses, so the
 * ratings here and the number at the top of the page cannot disagree.
 *
 * The rating is drawn as filled marks rather than a bar, and the number is
 * written beside them. A five-segment bar that only changes colour tells a
 * colour-blind reader nothing, and "4 of 5" is the fact anyway.
 *
 * Renders nothing when the analysis produced no section feedback — an empty
 * panel headed "Section feedback" reads as a failure rather than an absence.
 */
export function SectionFeedback({ sections }: { sections: SectionFeedbackItem[] }) {
  if (sections.length === 0) return null;

  return (
    <section className="flex flex-col gap-4">
      <PanelTitle>Section by section</PanelTitle>
      <Panel padded={false}>
        <ul className="flex flex-col m-0 p-0 list-none">
          {sections.map((section) => (
            <li
              key={section.section}
              className="flex flex-col gap-3 px-5 py-4 border-b border-line-subtle last:border-b-0"
            >
              <div className="flex items-center justify-between gap-4">
                <h3 className="text-base font-semibold text-primary m-0 capitalize">
                  {section.section.replace(/_/g, " ")}
                </h3>
                <Rating value={section.rating} />
              </div>

              {(section.strengths ?? []).length > 0 ? (
                <ul className="flex flex-col gap-1 m-0 p-0 list-none">
                  {(section.strengths ?? []).map((item, index) => (
                    <li key={index} className="flex gap-2 text-sm text-secondary leading-normal">
                      <span className="text-shown shrink-0" aria-hidden="true">
                        +
                      </span>
                      {item}
                    </li>
                  ))}
                </ul>
              ) : null}

              {(section.issues ?? []).length > 0 ? (
                <ul className="flex flex-col gap-1 m-0 p-0 list-none">
                  {(section.issues ?? []).map((item, index) => (
                    <li key={index} className="flex gap-2 text-sm text-secondary leading-normal">
                      <span className="text-capped shrink-0" aria-hidden="true">
                        −
                      </span>
                      {item}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      </Panel>
    </section>
  );
}

function Rating({ value }: { value: number }) {
  return (
    <span className="flex items-center gap-2 shrink-0">
      <span className="flex gap-1" aria-hidden="true">
        {[1, 2, 3, 4, 5].map((step) => (
          <span
            key={step}
            className={`w-2 h-2 rounded-full ${step <= value ? "bg-shown" : "bg-line-strong"}`}
          />
        ))}
      </span>
      <span className="numeric text-sm text-muted">{value} of 5</span>
    </span>
  );
}
