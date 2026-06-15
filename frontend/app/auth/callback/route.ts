/**
 * OAuth callback — exchanges the PKCE code Supabase appended to the redirect
 * URL for a session, then sends the user back where they started.
 *
 * Supabase redirects here after Google sign-in: /auth/callback?code=...&next=...
 */
import { NextResponse } from "next/server";

import { createClient } from "@/lib/supabase/server";

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  // Where to land after sign-in. Only allow same-origin relative paths.
  const nextParam = searchParams.get("next") ?? "/";
  const next = nextParam.startsWith("/") ? nextParam : "/";

  if (code) {
    const supabase = await createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(`${origin}${next}`);
    }
  }

  // No code, or exchange failed — bounce to the sign-in error surface.
  return NextResponse.redirect(`${origin}/auth/auth-error`);
}
