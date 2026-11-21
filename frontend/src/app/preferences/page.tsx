import { PreferencesForm } from "@/app/preferences/PreferencesForm";
import { getPreferences } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function PreferencesPage() {
  const prefs = await getPreferences();
  if (!prefs) return <p className="text-stone-600">Aún no se han guardado preferencias.</p>;
  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Preferencias</h1>
      <p className="text-sm text-stone-600">Los cambios aplican desde la próxima búsqueda programada.</p>
      <PreferencesForm prefs={prefs} />
    </div>
  );
}
