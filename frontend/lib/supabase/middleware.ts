/**
 * Session refresh for middleware. Runs on every request to keep the auth cookie
 * fresh (required for SSR auth with @supabase/ssr). Does not gate routes — the
 * app is anonymous-friendly; sign-in only unlocks persistence.
 */
import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request });

  // Gracefully no-op if Supabase isn't configured yet (keeps the app running
  // before the env keys are added).
  if (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY) {
    return response;
  }

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options),
          );
        },
      },
    },
  );

  // Refreshes the session if expired. Do not run other code between creating the
  // client and this call (per Supabase SSR guidance).
  await supabase.auth.getUser();

  return response;
}
