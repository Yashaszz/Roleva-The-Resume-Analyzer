/**
 * The first thing a user sees. 7.17 and 7.18.
 *
 * The hero is a **sentence**, not a number. "You show two of the five things
 * this job calls essential" is the finding; 55 is a summary of it. Leading with
 * the number makes the page a scoreboard, and a scoreboard is what every
 * competitor already is.
 *
 * There is no dial. A circular progress ring is the category cliché and the
 * least informative way to render a value with three weighted components, all
 * of which are shown beside it instead.
 */
import type { AnalysisReport } from "@/lib/types";

type ScoreReport = AnalysisReport["scores"];
type Score = ScoreReport["overall"];
type ExpectedBand = NonNullable<ScoreReport["expected_bands"]>[number];

export function Verdict({
  scores,
  headline,
  body,
  roleTitle,
  requirementCount,
  degradedStages,
}: {
  scores: ScoreReport;
  /**
   * One sentence, set at display size. Both this and `body` are built by the
   * API from computed facts — never a model's prose.
   *
   * They are separate fields because the first draft rendered the whole verdict
   * paragraph at 46px, which is five sentences of display type and reads as a
   * wall rather than a headline. The fix belonged in the contract, not in a
   * substring on the client.
   */
  headline: string;
  /** The consequences, at reading size. */
  body: string;
  roleTitle: string;
  requirementCount: number;
  /**
   * Stages that failed. Needed here to explain *why* a score's confidence is
   * low: `Score.confidence` is the minimum of the stage confidence and the
   * parse confidence, so a single message covering both said "part of this
   * analysis was degraded" on reports where nothing had degraded at all — the
   * resume was simply hard to read.
   */
  degradedStages?: string[];
}) {
  const capped = scores.overall.cap_applied;
  const degraded = (degradedStages ?? []).length > 0;

  return (
    <header className="flex flex-col gap-8">
      <div className="flex flex-col lg:flex-row lg:items-end gap-8 lg:gap-14">
        <div className="flex-1 flex flex-col gap-4">
          <p className="label m-0">
            {roleTitle} · {requirementCount} requirements
          </p>
          <h1
            className="display m-0 max-w-[21ch]"
            style={{ fontSize: "var(--text-display)" }}
          >
            {headline}
          </h1>
          <p className="text-md text-secondary leading-normal m-0 max-w-[62ch]">{body}</p>
        </div>

        <div className="flex flex-col lg:items-end gap-1 shrink-0">
          <span className="label">Overall</span>
          <div className="flex items-baseline gap-2">
            <span
              className={`display ${capped ? "text-capped" : "text-primary"}`}
              style={{
                fontSize: "var(--text-hero)",
                lineHeight: 0.82,
                letterSpacing: "var(--tracking-hero)",
              }}
            >
              {format(scores.overall.value)}
            </span>
            <span className="numeric text-sm text-muted">/100</span>
          </div>
          <span
            className={`text-base font-semibold ${capped ? "text-capped" : "text-secondary"}`}
          >
            {bandLabel(scores.overall.band)}
            {capped ? " · capped" : ""}
          </span>
        </div>
      </div>

      {capped ? (
        <div className="flex gap-3 p-4 bg-capped-bg border-l-2 border-capped rounded-r-sm">
          <svg
            width="17"
            height="17"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--status-capped)"
            strokeWidth="1.7"
            aria-hidden="true"
            className="shrink-0 mt-0.5"
          >
            <path d="M12 3 2 21h20L12 3z" />
            <path d="M12 10v5M12 18h.01" />
          </svg>
          {/* The cap text comes from the scoring engine, which states the
              coverage that triggered it. Shown verbatim. */}
          <p className="text-base text-secondary leading-normal m-0">{capped}</p>
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-3">
        <ScoreTile
          score={scores.job_match}
          label="Job match"
          band={findBand(scores.expected_bands, "job_match")}
          degraded={degraded}
        />
        <ScoreTile
          score={scores.quality}
          label="Writing"
          band={findBand(scores.expected_bands, "quality")}
          degraded={degraded}
        />
        <ScoreTile
          score={scores.ats}
          label="ATS parsing"
          band={findBand(scores.expected_bands, "ats")}
          degraded={degraded}
        />
      </div>
    </header>
  );
}

/**
 * One component score with its reference range. 7.19.
 *
 * The range is always labelled "typical", never a percentile. Roleva has no
 * cohort data until real users generate it, and a made-up "top 20%" would be
 * exactly the kind of confident nonsense this product exists to replace. Real
 * percentiles appear only above 30 samples.
 */
function ScoreTile({
  score,
  label,
  band,
  degraded,
}: {
  score: Score;
  label: string;
  band: ExpectedBand | null;
  degraded: boolean;
}) {
  const capped = Boolean(score.cap_applied);

  return (
    <div className="flex flex-col gap-2 p-4 bg-panel border border-line-subtle rounded-md">
      <span className="label">{label}</span>
      <div className="flex items-baseline gap-2">
        <span
          className={`numeric ${capped ? "text-capped" : "text-primary"}`}
          style={{ fontSize: "var(--text-2xl)", lineHeight: 1 }}
        >
          {format(score.value)}
        </span>
        {capped ? <span className="label text-capped">capped</span> : null}
      </div>

      {band ? (
        <span className="text-sm text-muted">
          Typical {format(band.low)}–{format(band.high)}
          {band.position === "above" ? " · above" : band.position === "below" ? " · below" : ""}
        </span>
      ) : null}

      {/* Confidence is only mentioned when it is not full. Saying "confidence
          100%" on every panel trains people to ignore the word — and naming the
          actual cause is the difference between a warning and a shrug. */}
      {score.confidence < 0.9 ? (
        <span className="text-sm text-capped">
          {degraded
            ? "Lower confidence — part of the analysis didn't finish"
            : "Lower confidence — parts of your resume were hard to read"}
        </span>
      ) : null}
    </div>
  );
}

function findBand(bands: ExpectedBand[] | undefined, kind: string): ExpectedBand | null {
  return bands?.find((band) => band.kind === kind) ?? null;
}

/** Whole numbers where possible: "55" reads better than "55.0". */
function format(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

const BANDS: Record<string, string> = {
  strong: "Strong candidate",
  competitive: "Competitive",
  needs_work: "Needs work",
  significant_gaps: "Significant gaps",
  not_aligned: "Not aligned",
};

function bandLabel(band: string): string {
  return BANDS[band] ?? band;
}
