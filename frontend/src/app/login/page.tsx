"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { createClient } from "@/lib/supabase/client";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError("");
    const { error } = await createClient().auth.signInWithPassword({ email, password });
    setPending(false);
    if (error) {
      setError(error.status === 429 ? "Demasiados intentos. Espera unos minutos e inténtalo de nuevo." : "Correo o contraseña incorrectos.");
      return;
    }
    const next = params.get("next") ?? "/";
    router.replace(next.startsWith("/") && !next.startsWith("//") ? next : "/");
    router.refresh();
  }

  return (
    <form onSubmit={submit} className="mt-6 space-y-3">
      <input
        type="email"
        required
        autoComplete="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="Correo electrónico"
        aria-label="Correo electrónico"
        className="w-full rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-stone-500 focus:outline-none"
      />
      <input
        type="password"
        required
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Contraseña"
        aria-label="Contraseña"
        className="w-full rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-stone-500 focus:outline-none"
      />
      <button
        disabled={pending}
        className="w-full rounded-md bg-stone-900 px-3 py-2 text-sm font-medium text-white hover:bg-stone-700 disabled:opacity-60"
      >
        {pending ? "Entrando…" : "Entrar"}
      </button>
      {error && <p className="text-sm text-red-700" role="alert">{error}</p>}
    </form>
  );
}

export default function LoginPage() {
  return (
    <div className="mx-auto mt-16 max-w-sm rounded-xl border border-stone-200 bg-white p-6 shadow-sm">
      <h1 className="text-xl font-semibold">HomeScout</h1>
      <p className="mt-1 text-sm text-stone-600">Panel privado.</p>
      <Suspense>
        <LoginForm />
      </Suspense>
    </div>
  );
}
