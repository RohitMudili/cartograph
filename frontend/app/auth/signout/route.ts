/**
 * Sign-out — clears the Supabase session and returns home. POST-only so a
 * stray prefetch or link crawl can't log the user out.
 */
import { NextResponse } from "next/server";

import { createClient } from "@/lib/supabase/server";

export async function POST(request: Request) {
  const supabase = await createClient();
  await supabase.auth.signOut();
  return NextResponse.redirect(new URL("/", request.url), { status: 303 });
}
