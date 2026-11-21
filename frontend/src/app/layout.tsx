import type { Metadata, Viewport } from "next";
import Link from "next/link";

import { signOut } from "@/app/actions";
import { getSessionEmail } from "@/lib/data";
import "./globals.css";

export const metadata: Metadata = {
  title: "HomeScout",
  description: "Private home search: ranked matches with evidence-backed analysis.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const email = await getSessionEmail();
  return (
    <html lang="en">
      <body className="min-h-screen bg-stone-50 text-stone-900 antialiased">
        {email && (
          <header className="sticky top-0 z-10 border-b border-stone-200 bg-white/90 backdrop-blur">
            <nav className="mx-auto flex max-w-5xl items-center gap-4 px-4 py-3 text-sm">
              <Link href="/" className="font-semibold tracking-tight">HomeScout</Link>
              <Link href="/" className="text-stone-600 hover:text-stone-900">Matches</Link>
              <Link href="/preferences" className="text-stone-600 hover:text-stone-900">Preferences</Link>
              <form action={signOut} className="ml-auto">
                <button className="text-stone-500 hover:text-stone-900" title={email}>Sign out</button>
              </form>
            </nav>
          </header>
        )}
        <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
