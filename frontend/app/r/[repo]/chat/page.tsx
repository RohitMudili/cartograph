import { ChatConsole } from "./ChatConsole";

// `params` is a Promise in this Next.js version — await it before use.
export default async function ChatPage({
  params,
}: {
  params: Promise<{ repo: string }>;
}) {
  const { repo } = await params;
  return <ChatConsole repoId={repo} />;
}
