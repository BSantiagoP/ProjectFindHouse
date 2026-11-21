import type { Property } from "@/lib/types";

const STYLES = {
  recomendada: { label: "Recomendada", cls: "bg-emerald-600 text-white" },
  considerar: { label: "Considerar", cls: "bg-amber-500 text-white" },
  no_recomendada: { label: "No recomendada", cls: "bg-stone-500 text-white" },
} as const;

export function VerdictBadge({ verdict }: { verdict: keyof typeof STYLES }) {
  const s = STYLES[verdict];
  return <span className={`rounded-md px-2 py-0.5 text-xs font-semibold ${s.cls}`}>{s.label}</span>;
}

export function AgentSummaryBox({ summary }: { summary: NonNullable<Property["agent_summary"]> }) {
  return (
    <section className="rounded-xl border-2 border-stone-800 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-semibold">Resumen del agente</h2>
        <VerdictBadge verdict={summary.verdict} />
      </div>
      <p className="mt-2 text-stone-800">{summary.headline}</p>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold text-emerald-700">A favor</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-stone-700">
            {summary.reasons_for.map((r) => <li key={r}>{r}</li>)}
          </ul>
        </div>
        <div>
          <h3 className="text-sm font-semibold text-red-700">En contra / riesgos</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-stone-700">
            {summary.reasons_against.map((r) => <li key={r}>{r}</li>)}
          </ul>
        </div>
      </div>
      {summary.next_steps.length > 0 && (
        <div className="mt-3">
          <h3 className="text-sm font-semibold">Próximos pasos</h3>
          <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm text-stone-700">
            {summary.next_steps.map((r) => <li key={r}>{r}</li>)}
          </ol>
        </div>
      )}
      <p className="mt-3 text-xs text-stone-500">
        Escrito por IA usando solo los datos calculados abajo; cada cifra se verifica contra esos datos.
        {summary.verdict_adjusted && " El veredicto se limitó a “Considerar” porque faltan datos por verificar."}
      </p>
    </section>
  );
}
