/**
 * The landing page. 7.11.
 *
 * What this is not: navbar → hero → gradient → feature cards → testimonials →
 * pricing → footer. That shape was ruled out at the start of the project, and
 * it is worth naming here because it is the path of least resistance and it
 * creeps back one section at a time.
 *
 * What it is instead: the product, demonstrated. The thread map halfway down is
 * the real component rendering a real analysis — the same fixture the report
 * preview uses, produced by the actual pipeline. Nobody has to believe a claim
 * about what Roleva does when they can look at what it did.
 *
 * The demo costs nothing to serve: it is a static import, so the landing page
 * runs no analysis and spends no model quota however many people open it.
 */
import Link from "next/link";

import { ThreadMap, type ThreadRow } from "@/components/report/Thread";
import { ButtonLink } from "@/components/ui/Button";
import fixture from "@/lib/fixtures/report.json";
import type { AnalysisReport } from "@/lib/types";

export const metadata = {
  title: "Roleva — see why your resume does or doesn't match a job",
  description:
    "Upload a resume, paste a job description, and see which requirements your own words actually support — and which ones nothing in your resume backs up.",
  // The only page in the product that is meant to be found.
  robots: { index: true, follow: true },
};

const demo = fixture as unknown as AnalysisReport;

export default function LandingPage() {
  return (
    <div className="flex flex-col">
      <header className="mx-auto w-full max-w-[1100px] px-5 sm:px-8 py-5 flex items-center justify-between gap-4">
        <span className="display text-lg">Roleva</span>
        <nav aria-label="Account">
          {/* Padded to a 44px target. A standalone nav link is not "inline in
              a sentence", so the target-size exception does not apply to it. */}
          <Link
            href="/sign-in"
            className="inline-flex items-center min-h-[44px] px-3 -mr-3 text-sm text-secondary no-underline hover:text-primary rounded-sm"
          >
            Sign in
          </Link>
        </nav>
      </header>

      {/* The argument, in one sentence. No sub-headline restating it, no badge
          above it, no gradient behind it. */}
      <section className="mx-auto w-full max-w-[1100px] px-5 sm:px-8 pt-10 sm:pt-20 pb-14 flex flex-col gap-8">
        <h1
          className="display m-0 max-w-[17ch]"
          style={{ fontSize: "var(--text-display)" }}
        >
          Most rejections never explain themselves.
        </h1>

        <p className="text-md text-secondary leading-normal max-w-[58ch] m-0">
          Roleva reads a job posting and your resume separately, then looks for each
          requirement in your own words. Where it finds evidence, it says where. Where it
          finds none, it says that too — which is usually the part nobody tells you.
        </p>

        <div className="flex flex-col sm:flex-row gap-3 sm:items-center">
          <ButtonLink href="/sign-up" variant="primary">
            Analyse my resume
          </ButtonLink>
          <span className="text-sm text-muted">
            Free · five analyses a day · your PDF is never stored
          </span>
        </div>
      </section>

      {/* The demonstration. A real component, real data, no explanation needed
          beyond the one line above it. */}
      <section className="border-y border-line-subtle bg-panel/40">
        <div className="mx-auto w-full max-w-[1100px] px-5 sm:px-8 py-14 flex flex-col gap-6">
          <div className="flex flex-col gap-2 max-w-[58ch]">
            <span className="label">A real analysis</span>
            <p className="text-md text-secondary leading-normal m-0">
              Every thread below was drawn by matching one requirement against one line
              of a resume. The ones that stop at an open circle found nothing — and that
              absence is the finding, not an omission.
            </p>
          </div>

          <ThreadMap rows={demoRows()} />
        </div>
      </section>

      {/* Three claims, each of which the product can be held to. Not feature
          cards: no icons, no equal-height boxes, no "Learn more". */}
      <section className="mx-auto w-full max-w-[1100px] px-5 sm:px-8 py-16 flex flex-col gap-12">
        <Claim
          heading="Every number points at a line you wrote"
          body="Open any score and it breaks into the requirements that produced it. Open a requirement and it quotes the sentence from your resume that satisfied it, with the section and page. Nothing is asserted that cannot be traced."
        />
        <Claim
          heading="Listing a skill is not the same as showing it"
          body="A tool named in your skills row scores differently from one you describe using. That gap — the thing you claim versus the thing you evidence — is the most common reason a resume reads thinner than the person behind it."
        />
        <Claim
          heading="No score is a language model's opinion of you"
          body="A model reads your resume and the posting into a structure. Every number after that is arithmetic over published weights, and the same inputs always produce the same score. The suggested rewrites are checked against your own text and dropped if they invent anything."
        />
      </section>

      <footer className="border-t border-line-subtle">
        <div className="mx-auto w-full max-w-[1100px] px-5 sm:px-8 py-8 flex flex-col sm:flex-row gap-4 sm:items-center sm:justify-between">
          <span className="text-sm text-muted">
            Roleva reads your resume. It does not keep the file.
          </span>
          <Link
            href="/sign-up"
            className="inline-flex items-center min-h-[44px] text-sm text-shown no-underline rounded-sm w-fit"
          >
            Start an analysis →
          </Link>
        </div>
      </footer>
    </div>
  );
}

function Claim({ heading, body }: { heading: string; body: string }) {
  return (
    <div className="flex flex-col sm:flex-row gap-4 sm:gap-10">
      <h2
        className="display m-0 sm:w-[38%] shrink-0"
        style={{ fontSize: "var(--text-lg)" }}
      >
        {heading}
      </h2>
      <p className="text-base text-secondary leading-normal m-0 max-w-[58ch]">{body}</p>
    </div>
  );
}

/**
 * The demo rows, from the committed fixture.
 *
 * Trimmed to eight so the map reads at a glance on a landing page rather than
 * asking for the study a full report deserves. Sorted the same way the report
 * sorts: the problems first.
 */
function demoRows(): ThreadRow[] {
  const requirements = demo.job.requirements ?? [];
  const matches = demo.matches.matches ?? [];
  const byId = new Map(matches.map((match) => [match.requirement_id, match]));

  const priority = { must: 0, strong: 1, nice: 2 } as const;
  const stateRank = { absent: 0, listed: 1, shown: 2 } as const;

  return requirements
    .map((requirement): ThreadRow => {
      const match = byId.get(requirement.id ?? "");
      const strength = match?.strength ?? 0;
      const best = match?.evidence?.[0];
      return {
        id: requirement.id ?? requirement.text,
        requirement: requirement.text,
        priority: requirement.priority,
        state:
          !match || match.status === "missing" || strength === 0
            ? "absent"
            : match.status === "partial" || strength <= 0.5
              ? "listed"
              : "shown",
        evidence: best?.span.text,
        location: best ? "Experience" : undefined,
      };
    })
    .sort(
      (a, b) =>
        priority[a.priority] - priority[b.priority] ||
        stateRank[a.state] - stateRank[b.state],
    )
    .slice(0, 8);
}
