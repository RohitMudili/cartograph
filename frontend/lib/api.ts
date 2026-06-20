/**
 * Typed client for the Cartograph backend API.
 *
 * Mirrors the FastAPI response models (app/api/repos.py). Kept hand-written and
 * small; if the surface grows, generate from the OpenAPI schema instead.
 *
 * When a user is signed in via Supabase Auth, the Supabase access token is sent
 * as an Authorization: Bearer header so the backend can validate it and
 * attribute repos/questions to the user (owner_user_id).
 */

import { createClient } from "./supabase/client";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type RepoStatus =
  | "pending"
  | "cloning"
  | "parsing"
  | "summarizing"
  | "indexed"
  | "failed";

export interface Repo {
  id: string;
  url: string;
  status: RepoStatus;
  head_commit: string | null;
  default_branch: string | null;
  indexed_at: string | null;
  stats: {
    files_total?: number;
    files_parsed?: number;
    nodes?: number;
    edges?: number;
    chunks?: number;
    summarized?: number;
    size_bytes?: number;
  };
}

export interface IndexResult {
  repo_id: string;
  run_id: string;
  head_commit: string;
  nodes: number;
  edges: number;
  chunks: number;
  files: number;
}

export interface Citation {
  path: string;
  start_line: number;
  end_line: number;
  verified: boolean;
}

export interface AnswerResponse {
  question: string;
  answer: string;
  route: string;
  answerable: boolean;
  fully_verified: boolean;
  citations: Citation[];
  used_nodes: number[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

/** Get the Supabase access token for the currently signed-in user, if any. */
async function getAccessToken(): Promise<string | null> {
  try {
    const supabase = createClient();
    const { data } = await supabase.auth.getSession();
    return data.session?.access_token ?? null;
  } catch {
    return null;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await getAccessToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { ...headers, ...init?.headers },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  indexRepo: (url: string, branch?: string) =>
    request<IndexResult>("/api/repos", {
      method: "POST",
      body: JSON.stringify({ url, branch }),
    }),

  getRepo: (id: string) => request<Repo>(`/api/repos/${id}`),

  ask: (repoId: string, question: string) =>
    request<AnswerResponse>(`/api/repos/${repoId}/questions`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
};
