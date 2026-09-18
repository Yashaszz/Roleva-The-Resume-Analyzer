import { checkHealth } from "@/lib/api";

/**
 * Placeholder shell.
 *
 * Intentionally plain. The visual identity is decided in the design phase,
 * after exploring several directions — putting a look here now would quietly
 * become the design by default. What this page proves is that the frontend
 * boots, the tokens load, and the browser can reach the API through the BFF.
 */
export default async function Home() {
  const health = await checkHealth();

  const label: Record<typeof health.state, string> = {
    ok: "Connected",
    waking: "Waking up",
    down: "Unreachable",
  };

  const color: Record<typeof health.state, string> = {
    ok: "var(--success)",
    waking: "var(--warning)",
    down: "var(--danger)",
  };

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-6 px-4 py-16">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Roleva</h1>
        <p className="mt-2 text-[color:var(--text-secondary)]">
          See how well your resume matches a specific job — and exactly why.
        </p>
      </div>

      <div
        className="rounded-[var(--radius-lg)] border p-4"
        style={{
          borderColor: "var(--line-subtle)",
          background: "var(--surface-raised)",
        }}
      >
        <div className="flex items-center gap-2 text-sm">
          {/* Shape plus text, never colour alone. */}
          <span aria-hidden="true" style={{ color: color[health.state] }}>
            ●
          </span>
          <span className="font-medium">API: {label[health.state]}</span>
          {health.state === "ok" && (
            <span className="text-[color:var(--text-muted)]">({health.environment})</span>
          )}
        </div>
        <p className="mt-2 text-sm text-[color:var(--text-muted)]">
          Build in progress. Upload and analysis land in a later phase.
        </p>
      </div>
    </main>
  );
}
