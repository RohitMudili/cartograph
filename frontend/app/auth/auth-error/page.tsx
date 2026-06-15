import Link from "next/link";

export default function AuthErrorPage() {
  return (
    <main className="flex min-h-[100dvh] flex-col items-center justify-center gap-4 bg-bg px-6 text-center text-ink">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted">Sign-in</p>
      <h1 className="text-2xl font-medium tracking-tight">Could not complete sign-in</h1>
      <p className="max-w-sm text-sm text-muted">
        The sign-in link may have expired or already been used. Head back and try again.
      </p>
      <Link
        href="/"
        className="mt-2 text-sm text-primary underline-offset-4 hover:underline"
      >
        Back to Cartograph
      </Link>
    </main>
  );
}
