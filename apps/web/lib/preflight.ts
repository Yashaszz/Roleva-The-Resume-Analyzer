/**
 * Client-side checks before an upload leaves the browser.
 *
 * Every one of these is repeated on the server, and the server's answer is the
 * one that counts — this is not a security boundary and is not trying to be.
 * It exists because a user on a phone connection should find out that their file
 * is 40 MB *before* spending ninety seconds uploading it, and because the error
 * they see can be specific in a way a generic 400 cannot.
 *
 * The rule for every message here: say what is wrong, and say what to do about
 * it. "Invalid file" fails both halves.
 */

/** Kept in step with `Settings.max_upload_bytes` on the API. */
export const MAX_BYTES = 8 * 1024 * 1024;

/** Kept in step with `Settings.min_jd_chars` / `warn_jd_chars`. */
export const MIN_JD_CHARS = 200;
export const GOOD_JD_CHARS = 600;

export type Rejection = { title: string; detail: string };

/**
 * Inspects the first bytes of the file rather than trusting its name or its
 * reported MIME type. A `.pdf` extension is a claim; `%PDF-` is evidence.
 */
export async function checkPdf(file: File): Promise<Rejection | null> {
  if (file.size === 0) {
    return {
      title: "That file is empty",
      detail: "It has no contents at all. Check you picked the right file.",
    };
  }

  if (file.size > MAX_BYTES) {
    const mb = (file.size / 1024 / 1024).toFixed(1);
    return {
      title: `That file is ${mb} MB`,
      detail:
        "The limit is 8 MB. Resumes are usually well under 1 MB — a large one " +
        "normally means embedded images. Re-export it, or use “Reduce file size” " +
        "if you are exporting from Preview or Acrobat.",
    };
  }

  const head = new Uint8Array(await file.slice(0, 1024).arrayBuffer());
  const magic = String.fromCharCode(...head.slice(0, 5));

  if (magic !== "%PDF-") {
    // The commonest mistakes have their own messages, because "not a PDF" does
    // not tell someone who just exported a .docx what to do next.
    const name = file.name.toLowerCase();
    if (name.endsWith(".doc") || name.endsWith(".docx")) {
      return {
        title: "That's a Word document",
        detail:
          "Roleva reads PDFs. In Word, use File → Save as → PDF, then upload that.",
      };
    }
    if (name.endsWith(".pages")) {
      return {
        title: "That's a Pages document",
        detail: "In Pages, use File → Export To → PDF, then upload that.",
      };
    }
    if (/\.(png|jpe?g|heic|webp)$/.test(name)) {
      return {
        title: "That's an image",
        detail:
          "Roleva needs the text of your resume, which an image does not contain. " +
          "Export a PDF from whatever you wrote it in.",
      };
    }
    return {
      title: "That doesn't look like a PDF",
      detail:
        "The file does not start the way a PDF does, whatever its name says. " +
        "Try re-exporting it.",
    };
  }

  // `/Encrypt` in the trailer means the document is password-protected or
  // permission-restricted. Caught here because a user who knows their file has
  // a password can fix it in seconds; a server-side rejection after a 4 MB
  // upload is the same information, later.
  const tail = new Uint8Array(await file.slice(Math.max(0, file.size - 2048)).arrayBuffer());
  const trailer = String.fromCharCode(...tail);
  if (trailer.includes("/Encrypt")) {
    return {
      title: "That PDF is password-protected",
      detail:
        "Roleva cannot open it. Save an unlocked copy — printing it to PDF " +
        "again usually removes the protection.",
    };
  }

  return null;
}

export type JdQuality = "short" | "thin" | "ok";

/**
 * How usable a pasted job description is.
 *
 * Deliberately three states rather than a percentage. The question in the user's
 * head is "is this enough yet", not "how full is the bar", and a bar that only
 * changes colour tells a colour-blind user nothing.
 */
export function jdQuality(text: string): JdQuality {
  const length = text.trim().length;
  if (length < MIN_JD_CHARS) return "short";
  if (length < GOOD_JD_CHARS) return "thin";
  return "ok";
}

/**
 * Warns about a paste that is missing the part Roleva actually reads.
 *
 * Someone who copies only the "About us" section gets a technically valid
 * posting with no requirements in it, and a confusing report. Cheap to detect,
 * and worth saying before they spend an analysis on it.
 */
export function jdWarning(text: string): string | null {
  if (jdQuality(text) === "short") return null;

  const lowered = text.toLowerCase();
  const signals = [
    "requirement",
    "qualification",
    "you will",
    "you'll",
    "experience",
    "skills",
    "responsibilit",
    "must have",
    "looking for",
  ];

  if (!signals.some((signal) => lowered.includes(signal))) {
    return (
      "This looks like it might be missing the requirements section. Roleva scores " +
      "against what the posting asks for, so include that part if you can."
    );
  }
  return null;
}
