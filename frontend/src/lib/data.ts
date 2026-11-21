import "server-only";

import { createClient } from "@/lib/supabase/server";
import type { Feedback, Preferences, Property, RunResult, SearchRun } from "@/lib/types";

type ResultRow = Omit<RunResult, "property"> & { properties: { data: Property } | null };

function toResult(row: ResultRow): RunResult | null {
  if (!row.properties) return null;
  const { properties, ...rest } = row;
  return { ...rest, property: properties.data };
}

export async function getLatestRun(): Promise<{ run: SearchRun; results: RunResult[] } | null> {
  const supabase = await createClient();
  const { data: runs, error } = await supabase
    .from("search_runs")
    .select("id,status,started_at,completed_at,requests_used,errors,counts")
    .neq("status", "failed")
    .order("started_at", { ascending: false })
    .limit(1);
  if (error) throw new Error(`Could not load runs: ${error.message}`);
  const run = runs?.[0] as SearchRun | undefined;
  if (!run) return null;
  const { data: rows, error: e2 } = await supabase
    .from("run_results")
    .select("property_id,filter_status,rejections,unverified,is_new,previous_price,analysis,rank,properties(data)")
    .eq("search_run_id", run.id);
  if (e2) throw new Error(`Could not load results: ${e2.message}`);
  const results = ((rows ?? []) as unknown as ResultRow[]).map(toResult).filter((r): r is RunResult => r !== null);
  return { run, results };
}

export async function getFeedbackMap(): Promise<Record<string, Feedback>> {
  const supabase = await createClient();
  const { data, error } = await supabase.from("property_feedback").select("property_id,liked,rejected,notes");
  if (error) throw new Error(`Could not load feedback: ${error.message}`);
  return Object.fromEntries((data ?? []).map((f) => [f.property_id, f as Feedback]));
}

export async function getPriceHistory(propertyId: string) {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("property_snapshots")
    .select("price,status,observed_at")
    .eq("property_id", propertyId)
    .order("observed_at", { ascending: true });
  if (error) throw new Error(`Could not load price history: ${error.message}`);
  return (data ?? []) as { price: number | null; status: string | null; observed_at: string }[];
}

export async function getPreferences(): Promise<Preferences | null> {
  const supabase = await createClient();
  const { data, error } = await supabase.from("search_preferences").select("data").eq("id", 1).maybeSingle();
  if (error) throw new Error(`Could not load preferences: ${error.message}`);
  return (data?.data as Preferences) ?? null;
}

export async function getSessionEmail(): Promise<string | null> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  return user?.email ?? null;
}
