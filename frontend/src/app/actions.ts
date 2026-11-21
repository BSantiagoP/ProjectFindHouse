"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

import { createClient } from "@/lib/supabase/server";

const FeedbackInput = z.object({
  propertyId: z.uuid(),
  verdict: z.enum(["liked", "rejected", "none"]),
});

export async function setFeedback(propertyId: string, verdict: "liked" | "rejected" | "none") {
  const input = FeedbackInput.parse({ propertyId, verdict });
  const supabase = await createClient();
  if (input.verdict === "none") {
    const { error } = await supabase.from("property_feedback").delete().eq("property_id", input.propertyId);
    if (error) throw new Error(error.message);
  } else {
    const { error } = await supabase.from("property_feedback").upsert({
      property_id: input.propertyId,
      liked: input.verdict === "liked",
      rejected: input.verdict === "rejected",
      updated_at: new Date().toISOString(),
    });
    if (error) throw new Error(error.message);
  }
  revalidatePath("/");
  revalidatePath(`/property/${input.propertyId}`);
}

// Same limits as backend/app/models/preferences.py so the scheduled job never reads invalid data.
const money = (min: number, max: number) => z.coerce.number().int().min(min).max(max);
const PreferencesInput = z.object({
  max_price: money(100_000, 5_000_000),
  target_monthly_cost: z.union([z.literal(""), money(500, 50_000)]),
  primary_scenario: z.enum(["fha_3_5", "conventional_5", "conventional_20"]),
  owner_unit: z.enum(["largest", "smallest"]),
  annual_insurance: money(0, 50_000),
  rate_override_pct: z.union([z.literal(""), z.coerce.number().min(1).max(15)]),
  towns: z.array(z.string().min(1)).min(1, "Elige al menos un pueblo"),
  commutes: z.record(z.string(), z.coerce.number().int().min(5).max(240)),
});

const FIELD_ES: Record<string, string> = {
  max_price: "Precio máximo",
  target_monthly_cost: "Meta mensual",
  primary_scenario: "Financiamiento",
  owner_unit: "Unidad donde vives",
  annual_insurance: "Seguro anual",
  rate_override_pct: "Tasa manual",
  towns: "Pueblos",
  commutes: "Minutos de trayecto",
};

export type PrefsState = { ok: boolean; message: string } | null;

export async function savePreferences(_prev: PrefsState, form: FormData): Promise<PrefsState> {
  const commutes: Record<string, FormDataEntryValue> = {};
  for (const [k, v] of form.entries()) if (k.startsWith("commute:")) commutes[k.slice(8)] = v;
  const parsed = PreferencesInput.safeParse({
    max_price: form.get("max_price"),
    target_monthly_cost: form.get("target_monthly_cost"),
    primary_scenario: form.get("primary_scenario"),
    owner_unit: form.get("owner_unit"),
    annual_insurance: form.get("annual_insurance"),
    rate_override_pct: form.get("rate_override_pct"),
    towns: form.getAll("towns"),
    commutes,
  });
  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    return { ok: false, message: `${FIELD_ES[String(issue.path[0])] ?? "Formulario"}: valor no válido${issue.path[0] === "towns" ? " (elige al menos un pueblo)" : ""}` };
  }
  const v = parsed.data;

  const supabase = await createClient();
  const { data: row, error } = await supabase.from("search_preferences").select("data").eq("id", 1).single();
  if (error || !row) return { ok: false, message: `No se pudieron cargar las preferencias actuales: ${error?.message}` };

  const current = row.data as Record<string, unknown> & { town_commutes: Record<string, { minutes: number }> };
  const town_commutes = { ...current.town_commutes };
  for (const [town, minutes] of Object.entries(v.commutes)) {
    if (town_commutes[town]) town_commutes[town] = { ...town_commutes[town], minutes };
  }
  const next = {
    ...current,
    max_price: v.max_price,
    target_monthly_cost: v.target_monthly_cost === "" ? null : v.target_monthly_cost,
    primary_scenario: v.primary_scenario,
    owner_unit: v.owner_unit,
    annual_insurance: v.annual_insurance,
    rate_override: v.rate_override_pct === "" ? null : Math.round(v.rate_override_pct * 100) / 10000,
    towns: v.towns,
    town_commutes,
  };
  const { data: updated, error: e2 } = await supabase
    .from("search_preferences")
    .update({ data: next, updated_at: new Date().toISOString() })
    .eq("id", 1)
    .select("id");
  if (e2) return { ok: false, message: e2.message };
  if (!updated?.length) return { ok: false, message: "No se guardó: esta cuenta no tiene permiso para editar preferencias." };
  revalidatePath("/preferences");
  return { ok: true, message: "Guardado. La próxima búsqueda usará estos ajustes y actualizará las puntuaciones." };
}

export async function signOut() {
  const supabase = await createClient();
  await supabase.auth.signOut();
  redirect("/login");
}
