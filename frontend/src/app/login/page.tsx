"use client";

import { useState } from "react";

import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [message, setMessage] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setState("sending");
    const next = new URLSearchParams(window.location.search).get("next") ?? "/";
    const { error } = await createClient().auth.signInWithOtp({
      email,
      options: {
        shouldCreateUser: false, // only pre-approved accounts can sign in
        emailRedirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`,
      },
    });
    if (error) {
      setState("error");
      setMessage("Could not send a link to that address.");
    } else {
      setState("sent");
    }
  }

  return (
    <div className="mx-auto mt-16 max-w-sm rounded-xl border border-stone-200 bg-white p-6 shadow-sm">
      <h1 className="text-xl font-semibold">HomeScout</h1>
      <p className="mt-1 text-sm text-stone-600">Private dashboard. Sign in with your email link.</p>
      {state === "sent" ? (
        <p className="mt-6 rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">
          Check your email for a sign-in link.
        </p>
      ) : (
        <form onSubmit={submit} className="mt-6 space-y-3">
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-stone-500 focus:outline-none"
          />
          <button
            disabled={state === "sending"}
            className="w-full rounded-md bg-stone-900 px-3 py-2 text-sm font-medium text-white hover:bg-stone-700 disabled:opacity-60"
          >
            {state === "sending" ? "Sending…" : "Email me a sign-in link"}
          </button>
          {state === "error" && <p className="text-sm text-red-700">{message}</p>}
        </form>
      )}
    </div>
  );
}
