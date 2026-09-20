/**
 * Dialog, Disclosure, Popover and Tooltip — all on Radix.
 *
 * Radix rather than hand-rolled because the parts that are hard here are the
 * parts nobody sees: focus trapping, restoring focus to the trigger on close,
 * `aria-expanded` staying in sync, Escape, scroll locking, and the fact that a
 * modal has to hide the rest of the page from a screen reader. Every one of
 * those is a bug I would otherwise ship.
 *
 * **On tooltips.** There is one here, and it is only for icon-only buttons. It is
 * never used for evidence: a tooltip is unreachable by keyboard on some
 * platforms, invisible on touch, and absent from print. `docs/DESIGN.md` §10
 * records that decision — evidence is shown, not hinted at.
 */
"use client";

import * as CollapsiblePrimitive from "@radix-ui/react-collapsible";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

/* ------------------------------------------------------------------ dialog -- */

export function Dialog({
  trigger,
  title,
  description,
  children,
  footer,
}: {
  trigger: ReactNode;
  title: string;
  /** Radix warns without one, and a dialog with no description is a dialog a
   *  screen reader announces as a bare title. */
  description: string;
  children?: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <DialogPrimitive.Root>
      <DialogPrimitive.Trigger asChild>{trigger}</DialogPrimitive.Trigger>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 bg-black/70 motion-safe:animate-[fade_var(--duration-quick)_var(--ease-out)]" />
        <DialogPrimitive.Content
          className={
            "fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 " +
            "w-[calc(100vw-32px)] max-w-[480px] " +
            "bg-panel border border-line-strong rounded-md p-6 " +
            "flex flex-col gap-4"
          }
        >
          <div className="flex flex-col gap-1.5">
            <DialogPrimitive.Title className="text-lg font-medium text-primary">
              {title}
            </DialogPrimitive.Title>
            <DialogPrimitive.Description className="text-sm text-secondary leading-normal">
              {description}
            </DialogPrimitive.Description>
          </div>

          {children}

          <div className="flex justify-end gap-2 pt-1">{footer}</div>

          <DialogPrimitive.Close
            aria-label="Close"
            className="absolute right-4 top-4 min-h-[36px] min-w-[36px] flex items-center justify-center text-muted hover:text-primary rounded-sm"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </DialogPrimitive.Close>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

export const DialogClose = DialogPrimitive.Close;

/* -------------------------------------------------------------- disclosure -- */

/**
 * The expand-to-see-the-arithmetic control.
 *
 * This is the interaction the report's explainability rests on: a score opens to
 * its components, a component opens to its evidence. It is a real button with
 * `aria-expanded`, so the state is announced rather than merely drawn.
 */
export function Disclosure({
  summary,
  children,
  defaultOpen = false,
  right,
}: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  right?: ReactNode;
}) {
  return (
    <CollapsiblePrimitive.Root defaultOpen={defaultOpen} className="border-b border-line-subtle last:border-b-0">
      <div className="flex items-center gap-3">
        <CollapsiblePrimitive.Trigger
          className={
            "group flex-1 flex items-center gap-2.5 min-h-[44px] py-2 text-left " +
            "text-primary hover:text-shown rounded-sm " +
            "transition-colors [transition-duration:var(--duration-instant)]"
          }
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            aria-hidden="true"
            className="shrink-0 text-muted group-hover:text-shown transition-transform [transition-duration:var(--duration-instant)] group-data-[state=open]:rotate-90"
          >
            <path d="m9 6 6 6-6 6" />
          </svg>
          {summary}
        </CollapsiblePrimitive.Trigger>
        {right}
      </div>
      <CollapsiblePrimitive.Content className="overflow-hidden pb-4">
        {children}
      </CollapsiblePrimitive.Content>
    </CollapsiblePrimitive.Root>
  );
}

/* ----------------------------------------------------------------- popover -- */

export function Popover({
  trigger,
  children,
  label,
}: {
  trigger: ReactNode;
  children: ReactNode;
  /** Names the popover for assistive technology. */
  label: string;
}) {
  return (
    <PopoverPrimitive.Root>
      <PopoverPrimitive.Trigger asChild>{trigger}</PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          aria-label={label}
          sideOffset={8}
          collisionPadding={16}
          className="w-[320px] max-w-[calc(100vw-32px)] bg-panel border border-line-strong rounded-md p-4 text-sm text-secondary leading-normal"
        >
          {children}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}

/* ----------------------------------------------------------------- tooltip -- */

/** Wrap the app once. Radix requires a provider above any tooltip. */
export function TooltipProvider({ children }: { children: ReactNode }) {
  return (
    <TooltipPrimitive.Provider delayDuration={300} skipDelayDuration={0}>
      {children}
    </TooltipPrimitive.Provider>
  );
}

/**
 * For icon-only buttons, and nothing else.
 *
 * The trigger must also carry its own `aria-label`: the tooltip is the visual
 * affordance, the label is the accessible name, and a tooltip alone leaves the
 * button unnamed on touch devices where it never appears.
 */
export function Tooltip({ trigger, children }: { trigger: ReactNode; children: string }) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{trigger}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          sideOffset={6}
          className="bg-inverse text-on-inverse text-xs px-2 py-1 rounded-sm font-medium"
        >
          {children}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
