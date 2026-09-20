/**
 * Score → components → contributions → evidence. 7.20.
 *
 * This is the control the product's central claim rests on. Every score opens
 * to the arithmetic that produced it, and every line of that arithmetic names
 * the requirement it came from. A user who does not believe a number can walk
 * down to the sentence in their own resume that caused it, in three clicks,
 * without leaving the page.
 *
 * The contributions are shown as signed point values rather than percentages,
 * because they *are* point values: the engine computes weight × strength and
 * these are those products. Rendering them as percentages would be a second
 * representation nobody could reconcile with the total.
 */
import { Disclosure } from "@/components/ui/Overlay";
import { Panel, PanelTitle } from "@/components/ui/Panel";
import type { AnalysisReport } from "@/lib/types";

type ScoreReport = AnalysisReport["scores"];
type Score = ScoreReport["overall"];
type ScoreComponent = NonNullable<Score["components"]>[number];

export function ScoreBreakdown({ scores }: { scores: ScoreReport }) {
  return (
    <section className="flex flex-col gap-4">
      <PanelTitle>Where each number comes from</PanelTitle>
      <Panel padded={false} className="px-5">
        <Breakdown score={scores.job_match} label="Job match" />
        <Breakdown score={scores.quality} label="Writing quality" />
        <Breakdown score={scores.ats} label="ATS parsing" />
      </Panel>
      <p className="text-sm text-muted leading-normal max-w-[68ch]">
        Overall is job match 45%, writing 35%, ATS 20% — then capped if essential
        requirements have no evidence. The weights are published in{" "}
        <code className="font-mono text-xs">rubric.yaml</code> and stamped into every
        report, so an old score can still be explained after they change.
      </p>
    </section>
  );
}

function Breakdown({ score, label }: { score: Score; label: string }) {
  const components = score.components ?? [];
  const capped = Boolean(score.cap_applied);

  return (
    <Disclosure
      summary={
        <span className="flex items-baseline gap-3 flex-1">
          <span className="text-base">{label}</span>
          <span className={`numeric text-base ${capped ? "text-capped" : "text-secondary"}`}>
            {score.value.toFixed(1)}
          </span>
          {capped && score.uncapped_value != null ? (
            <span className="label text-capped">
              capped from {score.uncapped_value.toFixed(1)}
            </span>
          ) : null}
        </span>
      }
    >
      {components.length === 0 ? (
        // An empty breakdown is a real state — an ATS score of 100 has no
        // findings — and it needs a sentence, not a blank panel that reads as a
        // loading failure.
        <p className="pl-[22px] text-sm text-muted m-0">
          Nothing to show here: no deductions and no findings.
        </p>
      ) : (
        <ul className="pl-[22px] flex flex-col m-0 p-0 list-none">
          {components.map((component) => (
            <Contribution key={component.key} component={component} />
          ))}
        </ul>
      )}
    </Disclosure>
  );
}

function Contribution({ component }: { component: ScoreComponent }) {
  const value = component.contribution;
  const positive = value > 0;

  return (
    <li className="flex items-start gap-3 py-2 border-b border-line-subtle last:border-b-0">
      <span
        className={`numeric text-sm shrink-0 w-[58px] text-right ${
          positive ? "text-shown" : value < 0 ? "text-absent" : "text-muted"
        }`}
      >
        {positive ? "+" : ""}
        {value.toFixed(2)}
      </span>

      <span className="flex-1 min-w-0 flex flex-col gap-0.5">
        <span className="text-sm text-primary">{component.label}</span>
        {component.detail ? (
          <span className="text-sm text-muted leading-snug">{component.detail}</span>
        ) : null}
      </span>

      {/* How the value was produced. A user can see at a glance which parts of
          their score were counted and which were judged — and there is exactly
          one of the latter. */}
      <span className="label shrink-0 pt-0.5" title={PROVENANCE[component.provenance]}>
        {component.provenance}
      </span>
    </li>
  );
}

const PROVENANCE: Record<string, string> = {
  rule: "A deterministic rule fired",
  computed: "Arithmetic over other values",
  lexical: "Exact, alias or fuzzy string match",
  semantic: "Embedding similarity",
  judged: "A model judged this",
  extracted: "A model extracted this into a schema",
};
