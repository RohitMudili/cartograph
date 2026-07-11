import { WalkthroughView } from "@/components/walkthrough/WalkthroughView";

// `params` is a Promise in this Next.js version — await it before use.
export default async function WalkthroughPage({
  params,
}: {
  params: Promise<{ repo: string }>;
}) {
  const { repo } = await params;
  return <WalkthroughView repoId={repo} />;
}
