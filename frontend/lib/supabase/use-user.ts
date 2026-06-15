"use client";

/**
 * Reactive Supabase user for Client Components. Reads the current session once,
 * then subscribes to auth changes (sign-in, sign-out, token refresh) so the UI
 * updates without a reload. Returns `{ user, loading }`.
 */
import type { User } from "@supabase/supabase-js";
import { useEffect, useState } from "react";

import { createClient } from "@/lib/supabase/client";

const supabaseConfigured =
  !!process.env.NEXT_PUBLIC_SUPABASE_URL && !!process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export function useUser() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(supabaseConfigured);

  useEffect(() => {
    if (!supabaseConfigured) return;
    const supabase = createClient();

    supabase.auth.getUser().then(({ data }) => {
      setUser(data.user);
      setLoading(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
      setLoading(false);
    });

    return () => subscription.unsubscribe();
  }, []);

  return { user, loading };
}
