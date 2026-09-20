/**
 * The primitives, on one page.
 *
 * Not a route users reach — a working reference for whoever is building the rest
 * of the product, and the page where a token change is checked before it reaches
 * twenty screens. Every primitive appears in every state it has, because the
 * states that go wrong are the ones nobody looks at: disabled, busy, errored,
 * empty.
 */
"use client";

import { Button, ButtonLink } from "@/components/ui/Button";
import { Input, LengthMeter, Textarea } from "@/components/ui/Field";
import { Empty, SkeletonGrid, SkeletonScore } from "@/components/ui/Loading";
import { Dialog, DialogClose, Disclosure, Popover, Tooltip, TooltipProvider } from "@/components/ui/Overlay";
import { EvidenceMark, Label, Panel, PanelTitle, Rule } from "@/components/ui/Panel";
import { ToastProvider, useToast } from "@/components/ui/Toast";
import { ThreadMap, type ThreadRow } from "@/components/report/Thread";

export default function DesignPage() {
  return (
    <TooltipProvider>
      <ToastProvider>
        <main className="mx-auto w-full max-w-[1280px] px-4 sm:px-8 py-10 flex flex-col gap-10">
          <header className="flex flex-col gap-2">
            <Label>Roleva · Direction D · Thread</Label>
            <h1 className="text-xl font-medium">Primitives</h1>
            <p className="text-sm text-secondary max-w-[68ch] leading-normal">
              Every component in every state. A token change is verified here before it
              reaches a screen.
            </p>
          </header>

          <Section title="Buttons">
            <div className="flex flex-wrap gap-3 items-center">
              <Button variant="primary">Analyse my resume</Button>
              <Button variant="secondary">Secondary</Button>
              <Button variant="ghost">Ghost</Button>
              <Button variant="danger">Delete analysis</Button>
            </div>
            <div className="flex flex-wrap gap-3 items-center">
              <Button variant="primary" busy>
                Analysing
              </Button>
              <Button variant="secondary" disabled>
                Disabled
              </Button>
              <Button variant="secondary" size="sm">
                Small
              </Button>
              <ButtonLink href="#" variant="secondary">
                A link that looks like a button
              </ButtonLink>
              <Tooltip trigger={<Button variant="ghost" size="sm" aria-label="Copy"><CopyIcon /></Button>}>
                Copy to clipboard
              </Tooltip>
            </div>
          </Section>

          <Section title="Fields">
            <div className="grid gap-6 sm:grid-cols-2">
              <Input label="Email" type="email" placeholder="you@example.com" required />
              <Input
                label="Email"
                type="email"
                defaultValue="not-an-email"
                error="That doesn't look like an email address."
              />
              <div className="sm:col-span-2">
                <Textarea
                  label="Job description"
                  hint="Paste the full posting, including requirements and responsibilities."
                  placeholder="Paste the job description here…"
                  meta={<LengthMeter length={412} min={200} good={600} />}
                />
              </div>
            </div>

            <div className="flex flex-col gap-2 pt-2">
              <Label>Length meter, all three states</Label>
              <LengthMeter length={140} min={200} good={600} />
              <LengthMeter length={412} min={200} good={600} />
              <LengthMeter length={1240} min={200} good={600} />
            </div>
          </Section>

          <Section title="Evidence states">
            <p className="text-sm text-secondary max-w-[68ch] leading-normal">
              Three states, and state is never carried by colour alone: each one has a
              mark and a word behind it, so the map survives greyscale printing and the
              common forms of colour blindness.
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 max-w-[560px]">
              <Cell state="shown" priority="MUST" name="Python" />
              <Cell state="listed" priority="MUST" name="PostgreSQL" />
              <Cell state="absent" priority="MUST" name="Docker" />
              <Cell state="shown" priority="NICE" name="Linux" />
            </div>
          </Section>

          <Section title="The thread map — this direction's signature">
            <p className="text-sm text-secondary max-w-[68ch] leading-normal">
              What the job asks on the left, what your resume actually says on the right,
              a thread between them where evidence was found. A thread that stops at an
              open circle found nothing — the absence has a shape rather than being one
              more red row in a list. The drawing is decorative: the same pairs are a
              real description list underneath, so a screen reader never touches it.
            </p>
            <ThreadMap rows={SAMPLE_ROWS} />
          </Section>

          <Section title="Disclosure — the explainability control">
            <Panel>
              <Disclosure
                defaultOpen
                summary={<span className="text-sm">Job match · 55.0</span>}
                right={<span className="numeric text-capped text-sm">CAPPED</span>}
              >
                <div className="pl-[22px] flex flex-col gap-2 pt-1">
                  <Row name="Python" value="1.00" state="shown" />
                  <Row name="PostgreSQL" value="0.50" state="listed" />
                  <Row name="Docker" value="0.00" state="absent" />
                </div>
              </Disclosure>
              <Disclosure summary={<span className="text-sm">Writing quality · 71.4</span>}>
                <div className="pl-[22px] text-sm text-secondary pt-1">
                  Seven counted metrics and one judged rubric.
                </div>
              </Disclosure>
            </Panel>
          </Section>

          <Section title="Overlays and toasts">
            <div className="flex flex-wrap gap-3 items-center">
              <Dialog
                trigger={<Button variant="danger">Delete analysis</Button>}
                title="Delete this analysis?"
                description="This removes the extracted resume data and the report. It cannot be undone."
                footer={
                  <>
                    <DialogClose asChild>
                      <Button variant="ghost">Keep it</Button>
                    </DialogClose>
                    <DialogClose asChild>
                      <Button variant="danger">Delete</Button>
                    </DialogClose>
                  </>
                }
              />
              <Popover
                label="How the score is computed"
                trigger={<Button variant="secondary">Where does 55 come from?</Button>}
              >
                Job match 45%, writing quality 35%, ATS parsing 20% — then capped at 55
                because two essential requirements have no evidence.
              </Popover>
              <ToastDemo />
            </div>
          </Section>

          <Section title="Loading and empty">
            <div className="grid gap-5 sm:grid-cols-3">
              <Panel>
                <SkeletonScore />
              </Panel>
              <Panel className="sm:col-span-2">
                <SkeletonGrid cells={14} />
              </Panel>
            </div>
            <Panel>
              <Empty
                title="No analyses yet"
                detail="Upload a resume and paste a job description, and the first one will appear here."
                action={<Button variant="primary">Start an analysis</Button>}
              />
            </Panel>
          </Section>

          <Section title="Type scale">
            <div className="flex flex-col gap-4">
              <div className="display text-capped" style={{ fontSize: "var(--text-hero)", letterSpacing: "var(--tracking-hero)" }}>
                55
              </div>
              <div className="display max-w-[21ch]" style={{ fontSize: "var(--text-display)" }}>
                You show <em className="italic text-shown">two</em> of the five things this job
                calls essential.
              </div>
              <div className="display text-xl">A section heading</div>
              <div className="numeric text-2xl">71.4</div>
              <div className="text-md text-secondary max-w-[68ch] leading-normal">
                Body copy at 16px. Nothing the user has to read runs wider than 68
                characters.
              </div>
              <div className="text-sm text-secondary">Small copy at 13px.</div>
              <Label>A mono label at 10px</Label>
            </div>
          </Section>
        </main>
      </ToastProvider>
    </TooltipProvider>
  );
}

/* ----------------------------------------------------------------- sample -- */

/**
 * The real output of the live run on 20 Sep, so the page is checked against
 * data the product actually produces rather than against tidy invented rows.
 */
const SAMPLE_ROWS: ThreadRow[] = [
  {
    id: "1",
    requirement: "Python",
    priority: "must",
    state: "shown",
    evidence: "Built a Django service handling 40,000 requests per day",
    location: "Experience, page 1",
  },
  {
    id: "2",
    requirement: "Testing",
    priority: "must",
    state: "shown",
    evidence: "Wrote 60 unit tests, raising coverage from 34% to 81%",
    location: "Experience, page 1",
  },
  { id: "3", requirement: "PostgreSQL", priority: "must", state: "listed" },
  { id: "4", requirement: "Docker", priority: "must", state: "absent" },
  { id: "5", requirement: "AWS", priority: "must", state: "absent" },
  {
    id: "6",
    requirement: "Django",
    priority: "strong",
    state: "shown",
    evidence: "Reduced p95 latency from 820ms to 210ms by adding indexes",
    location: "Experience, page 1",
  },
];

/* ---------------------------------------------------------------- helpers -- */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-4">
      <PanelTitle>{title}</PanelTitle>
      <Rule />
      <div className="flex flex-col gap-4 pt-1">{children}</div>
    </section>
  );
}

function Cell({
  state,
  priority,
  name,
}: {
  state: "shown" | "listed" | "absent";
  priority: string;
  name: string;
}) {
  // Border STYLE differs as well as colour. Measured in greyscale, the listed
  // and absent borders land at 54 and 48 — indistinguishable. Solid vs dashed
  // separates them without relying on hue at all.
  const style = {
    shown: "bg-shown text-on-signal border-transparent border-solid",
    listed: "bg-panel text-primary border-listed-line border-solid",
    absent: "bg-absent-bg text-absent border-absent-line border-dashed",
  }[state];

  return (
    <div className={`border rounded-sm p-2 h-[62px] flex flex-col justify-between ${style}`}>
      <div className="flex items-center justify-between gap-1">
        <span className="font-mono text-2xs tracking-[var(--tracking-label)]">{priority}</span>
        <EvidenceMark state={state} />
      </div>
      <span className="text-xs font-semibold">{name}</span>
    </div>
  );
}

function Row({
  name,
  value,
  state,
}: {
  name: string;
  value: string;
  state: "shown" | "listed" | "absent";
}) {
  const colour = {
    shown: "text-shown",
    listed: "text-primary",
    absent: "text-absent",
  }[state];

  return (
    <div className="flex items-center gap-3 text-sm">
      <span className={`flex items-center ${colour}`}>
        <EvidenceMark state={state} />
      </span>
      <span className="flex-1">{name}</span>
      <span className={`numeric ${colour}`}>{value}</span>
    </div>
  );
}

function ToastDemo() {
  const toast = useToast();
  return (
    <>
      <Button variant="secondary" onClick={() => toast("Copied to clipboard", "good")}>
        Show a toast
      </Button>
      <Button variant="ghost" onClick={() => toast("Analysis deleted")}>
        Neutral toast
      </Button>
    </>
  );
}

function CopyIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="1.5" />
      <path d="M5 15V5a1 1 0 0 1 1-1h9" />
    </svg>
  );
}
