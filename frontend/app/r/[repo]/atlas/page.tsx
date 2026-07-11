import { AtlasView } from "@/components/atlas/AtlasView";

// `params` is a Promise in this Next.js version — await it before use.
export default async function AtlasPage({
  params,
}: {
  params: Promise<{ repo: string }>;
}) {
  const { repo } = await params;
  return <AtlasView repoId={repo} />;
}
