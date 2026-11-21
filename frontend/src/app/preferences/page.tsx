import { PreferencesForm } from "@/app/preferences/PreferencesForm";
import { getPreferences } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function PreferencesPage() {
  const prefs = await getPreferences();
  if (!prefs) return <p className="text-stone-600">Preferences haven&apos;t been saved yet.</p>;
  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Preferences</h1>
      <p className="text-sm text-stone-600">Changes apply from the next scheduled search.</p>
      <PreferencesForm prefs={prefs} />
    </div>
  );
}
