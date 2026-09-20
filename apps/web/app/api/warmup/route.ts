/**
 * Wakes the API while the user is still filling in the form.
 *
 * Called from the analyze page on load. Render's free tier stops an idle
 * instance and takes up to fifty seconds to start it again; choosing a file and
 * pasting a posting takes about a minute. Overlapping the two makes most of the
 * cold start disappear.
 *
 * Unauthenticated on purpose — requiring a session would delay the wake-up
 * until after sign-in, which is most of the wait it exists to remove. It reads
 * no rows and reveals nothing.
 */

import { NextResponse } from "next/server";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export async function GET() {
  try {
    const response = await fetch(`${API_BASE_URL}/warmup`, {
      // A cold instance can take most of a minute; this is a hint, not a
      // dependency, so it gives up rather than holding a connection open.
      signal: AbortSignal.timeout(20_000),
      cache: "no-store",
    });
    return NextResponse.json({ awake: response.ok });
  } catch {
    // Failure here is not an error the user needs to know about: the analysis
    // request wakes the service anyway, just more slowly.
    return NextResponse.json({ awake: false });
  }
}
