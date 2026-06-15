/**
 * Next.js Proxy (formerly "middleware", renamed in Next 16).
 *
 * Runs before every matched request to keep the Supabase auth session cookie
 * fresh. It does not gate routes — Cartograph is anonymous-friendly; sign-in
 * only unlocks "my repos" + history.
 */
import { type NextRequest } from "next/server";
import { updateSession } from "@/lib/supabase/middleware";

export async function proxy(request: NextRequest) {
  return await updateSession(request);
}

export const config = {
  matcher: [
    // Run on everything except static assets, image optimization, and favicon.
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
