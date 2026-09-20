/**
 * The report. 7.17–7.27.
 *
 * Fetched on the server so the page arrives complete: a report is a document,
 * and a document that assembles itself in front of you after a thirty-second
 * wait is worse than one that simply appears.
 *
 * The order is the order a person reads in — verdict, then the gap, then the
 * detail, then what to do. Recommendations come before the full ledger because
 * "what should I change" is the question; "here is every requirement" is the
 * evidence for the answer.
 */
import { cookies } from "next/headers";
import { notFound } from "next/navigation";

import { AtsChecklist, BulletSuggestions, Recommendations } from "@/components/report/Advice";
import { ScoreBreakdown } from "@/components/report/ScoreBreakdown";
import { SkillLedger } from "@/components/report/SkillLedger";
import { ThreadMap, type ThreadRow } from "@/components/report/Thread";
import { Verdict } from "@/components/report/Verdict";
import { ToastProvider } from "@/components/ui/Toast";
import { serverClient } from "@/lib/supabase";
import type { AnalysisReport } from "@/lib/types";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

/** Reports contain resume content. Nothing here is ever indexable. */
export const metadata = { robots: { index: false, follow: false } };

export default async function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const report = await loadReport(id);
  if (!report) notFound();

  /*
   * Every collection below is optional in the generated schema, because the
   * API builds them from Pydantic default_factory fields which are therefore
   * not "required" in the JSON schema. They are normalised once here rather
   * than defended against in nine components.
   */
  const requirements = report.job.requirements ?? [];
  const matches = report.matches.matches ?? [];
  const rows = threadRows(requirements, matches);
  const degraded = report.degraded_stages ?? [];

  return (
    <ToastProvider>
      <main className="mx-auto w-full max-w-[1100px] px-5 sm:px-8 py-10 sm:py-14 flex flex-col gap-14">
        <Verdict
          scores={report.scores}
          headline={report.headline}
          body={report.verdict}
          roleTitle={roleTitle(report)}
          requirementCount={requirements.length}
          degradedStages={report.degraded_stages ?? []}
        />

        {/* The signature. Placed directly under the verdict because it is the
            evidence for the sentence the user just read. */}
        <ThreadMap rows={rows} />

        <Recommendations items={report.recommendations ?? []} />

        <BulletSuggestions suggestions={report.bullet_suggestions ?? []} />

        <SkillLedger
          requirements={requirements}
          matches={matches}
        />

        <AtsChecklist
          findings={report.ats.findings ?? []}
          checksRun={report.ats.checks_run}
          hiddenText={report.ats.hidden_text_detected}
        />

        <ScoreBreakdown scores={report.scores} />

        {degraded.length > 0 ? (
          <footer className="flex flex-col gap-2 p-4 bg-capped-bg border-l-2 border-capped rounded-r-sm">
            <p className="text-base text-secondary leading-normal m-0">
              Part of this analysis did not complete, so the report is thinner than
              usual. What is here is still computed the same way — nothing was guessed
              to fill a gap.
            </p>
            <p className="label m-0">
              Degraded: {degraded.join(", ")}
            </p>
          </footer>
        ) : null}
      </main>
    </ToastProvider>
  );
}

/**
 * Fetches one report as the signed-in user.
 *
 * The user's own token goes upstream, so the API applies RLS to them exactly as
 * it would in the browser. A report belonging to somebody else is a 404 from
 * the database, not a check written here.
 */
async function loadReport(id: string): Promise<AnalysisReport | null> {
  const store = await cookies();
  const supabase = serverClient({ getAll: () => store.getAll() });
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session) return null;

  try {
    const response = await fetch(`${API_BASE_URL}/analyses/${id}`, {
      headers: { Authorization: `Bearer ${session.access_token}` },
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as AnalysisReport;
  } catch {
    return null;
  }
}

/**
 * Turns requirements and matches into the thread map's rows.
 *
 * Essential requirements first, then by how much attention they need: a missing
 * must-have is the first thread on the page, a satisfied nice-to-have the last.
 * The drawing is not sorted for looks — it is sorted so the top-left corner is
 * where the problem is.
 */
function threadRows(
  requirements: NonNullable<AnalysisReport["job"]["requirements"]>,
  matches: NonNullable<AnalysisReport["matches"]["matches"]>,
): ThreadRow[] {
  const byId = new Map(matches.map((match) => [match.requirement_id, match]));

  const rows = requirements.map((requirement): ThreadRow => {
    const match = byId.get(requirement.id ?? "");
    const strength = match?.strength ?? 0;
    const best = match?.evidence?.[0];

    const state: ThreadRow["state"] =
      !match || match.status === "missing" || strength === 0
        ? "absent"
        : match.status === "partial" || strength <= 0.5
          ? "listed"
          : "shown";

    return {
      id: requirement.id ?? requirement.text,
      requirement: requirement.text,
      priority: requirement.priority,
      state,
      evidence: best?.span.text,
      location: best ? location(best.origin, best.span.page) : undefined,
    };
  });

  const priorityRank = { must: 0, strong: 1, nice: 2 } as const;
  const stateRank = { absent: 0, listed: 1, shown: 2 } as const;

  return rows.sort(
    (a, b) =>
      priorityRank[a.priority] - priorityRank[b.priority] ||
      stateRank[a.state] - stateRank[b.state],
  );
}

function location(origin: string, page: number | null | undefined): string {
  const where =
    {
      experience_bullet: "Experience",
      project_bullet: "Projects",
      certification: "Certifications",
      summary: "Summary",
      skills_list: "Skills",
      education: "Education",
    }[origin] ?? "Resume";

  return page ? `${where}, page ${page}` : where;
}

function roleTitle(report: AnalysisReport): string {
  const { title, company, seniority } = report.job;
  const base = title ?? "This role";
  const level = seniority && seniority !== "unknown" ? `, ${seniority}` : "";
  return company ? `${base} at ${company}${level}` : `${base}${level}`;
}
