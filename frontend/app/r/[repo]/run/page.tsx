import { MissionControl } from "@/components/mission/MissionControl";

// `params` is a Promise in this Next.js version — await it before use.
export default async function RunPage({
  params,
}: {
  params: Promise<{ repo: string }>;
}) {
  const { repo } = await params;
  return <MissionControl repoId={repo} />;
}
