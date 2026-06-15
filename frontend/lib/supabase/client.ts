/**
 * Supabase browser client — for Client Components.
 *
 * Uses the public anon key (safe in the browser). Session is stored in cookies
 * managed by @supabase/ssr so the server can read it too.
 */
import { createBrowserClient } from "@supabase/ssr";

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
