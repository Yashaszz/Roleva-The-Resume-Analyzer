/**
 * The resume dropzone.
 *
 * A real `<input type="file">` does the work; the dropzone is a label wrapped
 * around it. That is deliberate — a div with a click handler cannot be reached
 * by Tab, cannot be activated with Space, and is invisible to a screen reader.
 * Doing it this way means keyboard and assistive-technology support is not a
 * feature that had to be added.
 *
 * Drag-and-drop is an enhancement layered on top. On a phone — where most of
 * these uploads come from — there is nothing to drag, and the same control is
 * simply a large, obvious tap target.
 */
"use client";

import { useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { checkPdf, type Rejection } from "@/lib/preflight";

export function Dropzone({
  file,
  onFile,
  disabled,
}: {
  file: File | null;
  onFile: (file: File | null) => void;
  disabled?: boolean;
}) {
  const [dragging, setDragging] = useState(false);
  const [rejection, setRejection] = useState<Rejection | null>(null);
  const [checking, setChecking] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function accept(candidate: File | undefined) {
    if (!candidate) return;

    setChecking(true);
    setRejection(null);

    const problem = await checkPdf(candidate);

    setChecking(false);

    if (problem) {
      setRejection(problem);
      onFile(null);
      // Clear the input, so picking the *same* file again after fixing it still
      // fires a change event.
      if (inputRef.current) inputRef.current.value = "";
      return;
    }

    onFile(candidate);
  }

  if (file) {
    return (
      <div className="flex flex-col gap-2">
        <span className="label">Your resume</span>
        <div className="flex items-center gap-3 p-4 bg-good-bg border-l-2 border-shown rounded-r-sm">
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--evidence-shown)"
            strokeWidth="1.8"
            aria-hidden="true"
            className="shrink-0"
          >
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <path d="M14 2v6h6" />
          </svg>
          <div className="flex-1 min-w-0">
            <p className="text-base text-primary truncate m-0">{file.name}</p>
            <p className="numeric text-2xs text-muted m-0">
              {(file.size / 1024).toFixed(0)} KB
            </p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              onFile(null);
              if (inputRef.current) inputRef.current.value = "";
            }}
          >
            Replace
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <span className="label">Your resume</span>

      {/* The label IS the dropzone. Clicking anywhere on it opens the picker,
          because that is what a label does. */}
      <label
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (!disabled) void accept(e.dataTransfer.files[0]);
        }}
        className={
          "flex flex-col items-center justify-center gap-3 px-6 py-10 " +
          "border border-dashed rounded-md cursor-pointer text-center " +
          "transition-colors [transition-duration:var(--duration-instant)] " +
          "focus-within:outline focus-within:outline-2 focus-within:outline-[var(--focus-ring)] focus-within:outline-offset-2 " +
          (disabled ? "opacity-50 cursor-not-allowed " : "") +
          (dragging
            ? "border-shown bg-good-bg "
            : rejection
              ? "border-absent-line bg-absent-bg "
              : "border-line-strong hover:border-listed-line hover:bg-panel ")
        }
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          disabled={disabled}
          onChange={(e) => void accept(e.target.files?.[0])}
          // Visually hidden rather than display:none — a hidden input is not
          // focusable, which would take the keyboard path away again.
          className="sr-only"
        />

        <svg
          width="26"
          height="26"
          viewBox="0 0 24 24"
          fill="none"
          stroke={dragging ? "var(--evidence-shown)" : "var(--text-muted)"}
          strokeWidth="1.5"
          aria-hidden="true"
        >
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <path d="m7 10 5-5 5 5" />
          <path d="M12 5v12" />
        </svg>

        <div className="flex flex-col gap-1">
          <span className="text-base text-primary font-medium">
            {checking ? "Checking your file…" : "Drop your resume here, or choose a file"}
          </span>
          <span className="text-sm text-muted">PDF, up to 8 MB</span>
        </div>
      </label>

      {rejection ? (
        // role="alert" so the reason is announced, not just drawn.
        <div role="alert" className="flex flex-col gap-1 p-3 bg-absent-bg border-l-2 border-absent-line rounded-r-sm">
          <p className="text-base text-absent font-medium m-0">{rejection.title}</p>
          <p className="text-sm text-secondary leading-normal m-0">{rejection.detail}</p>
        </div>
      ) : null}
    </div>
  );
}
