/** Extended API client for The Sterling Syndicate CRM. */

// Normalize the configured base URL. Render's `fromService host` injects a bare
// hostname (e.g. "sterling-api.onrender.com") with no scheme; prepend https so
// fetch() targets an absolute URL instead of a same-origin relative path.
export function normalizeApiUrl(raw: string | undefined): string {
  const url = (raw ?? "http://127.0.0.1:8000").trim();
  if (!url) return "http://127.0.0.1:8000";
  if (/^https?:\/\//i.test(url)) return url.replace(/\/$/, "");
  return `https://${url.replace(/\/$/, "")}`;
}

const API_URL = normalizeApiUrl(import.meta.env.VITE_API_URL);

/** Error carrying the HTTP status so callers can distinguish e.g. a 404 from a 500. */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export type UserPublic = {
  id: string;
  name: string;
  email: string;
  skills: string[];
  portfolio_summary: string | null;
  role?: string;
  is_active: boolean;
  created_at: string;
};

export type TokenResponse = {
  /** Always empty — JWT is HttpOnly-cookie only. Kept for API shape compat. */
  access_token: string;
  token_type: string;
  user: UserPublic;
};

/** Allow only http(s) URLs for clickable external links (blocks javascript: etc.). */
export function safeExternalUrl(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  try {
    const u = new URL(trimmed);
    if (u.protocol === "http:" || u.protocol === "https:") return u.href;
  } catch {
    /* ignore */
  }
  return null;
}

export type PipelineStatus =
  | "new"
  | "drafting"
  | "sent"
  | "negotiating"
  | "won"
  | "lost"
  | "rejected_tos_violation"
  | "rejected_by_sast"
  | "pending_payment_verification"
  | "in_progress"
  | "paused_for_budget_extension"
  | "paused_for_captcha"
  | "delivered"
  | "paid"
  | "archived";

export type Lead = {
  id: string;
  source: string;
  title: string;
  raw_text: string;
  url: string | null;
  category: string | null;
  ingested_at: string;
  match_score: number | null;
  pipeline_status: PipelineStatus;
  tos_rejection_reason?: string | null;
};

export type Proposal = {
  id: string;
  lead_id: string;
  draft_text: string;
  status: string;
  generated_by: string;
  tone: string | null;
  created_at: string;
  sent_at: string | null;
  outcome?: string | null;
  recommended_bid?: number | null;
  rag_citations?: string | null;
};

export type Conversation = {
  id: string;
  lead_id: string;
  direction: string;
  body: string;
  label: string | null;
  generated_by: string;
  created_at: string;
};

export type ReplySuggestion = {
  label: string;
  body: string;
  generated_by: string;
  scope_creep_detected?: boolean;
  out_of_scope_summary?: string | null;
};

export type Deliverable = {
  id: string;
  contract_id: string;
  description: string;
  status: string;
  checklist: string[];
};

export type Contract = {
  id: string;
  lead_id: string;
  agreed_scope: string;
  agreed_price: number;
  currency: string;
  deadline: string | null;
  status: string;
  is_payment_verified: boolean;
  client_display_name: string | null;
  payment_claimed_at: string | null;
  payment_verified_at: string | null;
  effort_level: string;
  max_api_budget: number;
  cumulative_api_cost: number;
  budget_warning_sent: boolean;
  execution_draft: string | null;
  qa_status: string;
  completeness_pct: number;
  emergency_extensions: number;
  created_at: string;
  deliverables: Deliverable[];
};

export type ExecutionResult = {
  draft: string;
  model_used: string;
  cost_this_run: number;
  cumulative_api_cost: number;
  max_api_budget: number;
  budget_state: string;
  effort_level: string;
  qa: {
    passed: boolean;
    completeness_pct: number;
    issues: string;
    authorize_emergency_extension: boolean;
    summary: string;
    sast_passed?: boolean;
    sast_log?: string;
    ready_for_delivery?: boolean;
  } | null;
  paused: boolean;
  message: string;
  contract: Contract;
  sast_passed?: boolean;
  ready_for_delivery?: boolean;
};

export type AnalyticsSummary = {
  total_leads: number;
  proposals_sent: number;
  won: number;
  lost: number;
  win_rate: number;
  avg_hours_to_mark_sent: number | null;
  revenue_by_month: { month: string; revenue: number }[];
  revenue_by_category: { category: string; revenue: number }[];
};

async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  // CSRF guard for cookie sessions (required by backend CsrfGuardMiddleware).
  headers.set("X-Requested-With", "XMLHttpRequest");
  // Only attach Bearer for a real JWT — never for the "cookie" sentinel.
  // Production auth is cookie-only; Bearer remains for API/tools that still mint JWTs.
  if (token && token !== "cookie" && token.includes(".")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...options, headers, credentials: "include" });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (/failed to fetch|networkerror|load failed|network request failed/i.test(msg)) {
      throw new Error(
        `Cannot reach API. Is the backend running? ` +
          `(If Docker/Postgres is down, the API should auto-fall back to SQLite.)`,
      );
    }
    throw new Error(`Network error talking to API: ${msg}`);
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string | { msg: string }[] };
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d) => d.msg).join("; ");
    } catch {
      /* ignore */
    }
    if (res.status === 401) {
      // Expired/invalid token mid-session: force re-auth so the user
      // isn't stuck on every page. Skip for the auth endpoints (a wrong password
      // there is a normal 401, not a session expiry).
      if (!path.startsWith("/auth/login") && !path.startsWith("/auth/signup")) {
        window.dispatchEvent(new Event("sterling:unauthorized"));
      }
      throw new ApiError(res.status, detail || "Invalid credentials");
    }
    if (res.status === 409) {
      throw new ApiError(res.status, detail || "Email already registered");
    }
    // DB-outage message keyed on status code only — the old substring test
    // mislabeled ordinary 4xx errors whose detail mentioned "connection"/"database".
    if (res.status === 503 || res.status === 502 || res.status === 504) {
      throw new ApiError(res.status, `Database connection failed: ${detail}`);
    }
    throw new ApiError(res.status, detail || `Request failed (${res.status})`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const signup = (body: {
  name: string;
  email: string;
  password: string;
  skills?: string[];
  portfolio_summary?: string;
  invite_code?: string;
}) =>
  request<TokenResponse>("/auth/signup", { method: "POST", body: JSON.stringify(body) });

export const login = (body: { email: string; password: string }) =>
  request<TokenResponse>("/auth/login", { method: "POST", body: JSON.stringify(body) });

export const fetchMe = (token: string) =>
  request<UserPublic>("/auth/me", { method: "GET" }, token);

export const forgotPassword = (email: string) =>
  request<{ message: string }>("/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email }),
  });

export const resetPassword = (token: string, new_password: string) =>
  request<{ message: string }>("/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, new_password }),
  });

export const listLeads = (token: string, minScore?: number) => {
  const q = minScore != null ? `?min_score=${minScore}` : "";
  return request<Lead[]>(`/leads${q}`, {}, token);
};

export const getLead = (token: string, id: string) =>
  request<Lead>(`/leads/${id}`, {}, token);

export const pasteLead = (
  token: string,
  body: { title?: string; raw_text: string; url?: string; category?: string },
) =>
  request<Lead>("/leads/manual", { method: "POST", body: JSON.stringify(body) }, token);

export const ingestSource = (
  token: string,
  body: { source: "remoteok" | "weworkremotely"; limit?: number; tags?: string[] },
) =>
  request<Lead[]>("/leads/ingest", { method: "POST", body: JSON.stringify(body) }, token);

export const updateLeadStatus = (token: string, id: string, pipeline_status: PipelineStatus) =>
  request<Lead>(
    `/leads/${id}/status`,
    { method: "PATCH", body: JSON.stringify({ pipeline_status }) },
    token,
  );

export const draftProposal = (token: string, leadId: string, tone: string) =>
  request<Proposal>(
    `/leads/${leadId}/draft-proposal`,
    { method: "POST", body: JSON.stringify({ tone }) },
    token,
  );

export const listProposals = (token: string, leadId: string) =>
  request<Proposal[]>(`/leads/${leadId}/proposals`, {}, token);

export const markProposalSent = (token: string, proposalId: string) =>
  request<Proposal>(`/proposals/${proposalId}/mark-sent`, { method: "POST" }, token);

export const setProposalOutcome = (
  token: string,
  proposalId: string,
  outcome: "accepted" | "rejected",
) =>
  request<Proposal>(
    `/proposals/${proposalId}/outcome`,
    { method: "POST", body: JSON.stringify({ outcome }) },
    token,
  );

export const ingestGithubPortfolio = (
  token: string,
  username: string,
  max_repos = 8,
) =>
  request<{ upserted: number }>(
    "/portfolio/github",
    { method: "POST", body: JSON.stringify({ username, max_repos }) },
    token,
  );

export const suggestReplies = (token: string, leadId: string, body: string) =>
  request<ReplySuggestion[]>(
    `/conversations/${leadId}/suggest-replies`,
    { method: "POST", body: JSON.stringify({ body }) },
    token,
  );

export const listConversations = (token: string, leadId: string) =>
  request<Conversation[]>(`/conversations/${leadId}`, {}, token);

export const createContract = (
  token: string,
  leadId: string,
  body: {
    agreed_scope: string;
    agreed_price: number;
    currency?: string;
    deadline?: string;
    client_display_name?: string;
    deliverables?: { description: string; checklist?: string[] }[];
  },
) =>
  request<Contract>(
    `/leads/${leadId}/contract`,
    { method: "POST", body: JSON.stringify(body) },
    token,
  );

export const getContract = (token: string, leadId: string) =>
  request<Contract>(`/leads/${leadId}/contract`, {}, token);

export const updateDeliverable = (
  token: string,
  id: string,
  body: { status: string; checklist?: string[] },
) =>
  request<Deliverable>(
    `/deliverables/${id}`,
    { method: "PATCH", body: JSON.stringify(body) },
    token,
  );

export const markPaid = (token: string, leadId: string) =>
  request<Contract>(`/leads/${leadId}/mark-paid`, { method: "POST" }, token);

export const claimPayment = (
  token: string,
  leadId: string,
  body?: { client_display_name?: string; amount?: number },
) =>
  request<Contract>(
    `/leads/${leadId}/payment-claimed`,
    { method: "POST", body: JSON.stringify(body ?? {}) },
    token,
  );

export const confirmPayment = (token: string, leadId: string, mfa_code?: string) =>
  request<Contract>(`/leads/${leadId}/confirm-payment`, {
    method: "POST",
    body: JSON.stringify(mfa_code ? { mfa_code } : {}),
  }, token);

export const runExecution = (
  token: string,
  leadId: string,
  body?: { task_prompt?: string; run_qa?: boolean },
) =>
  request<ExecutionResult>(
    `/leads/${leadId}/execute`,
    { method: "POST", body: JSON.stringify(body ?? {}) },
    token,
  );

export const authorizeBudgetExtension = (
  token: string,
  leadId: string,
  extra_ratio = 0.05,
) =>
  request<Contract>(
    `/leads/${leadId}/authorize-budget-extension`,
    { method: "POST", body: JSON.stringify({ extra_ratio }) },
    token,
  );

export const fetchAnalytics = (token: string) =>
  request<AnalyticsSummary>("/analytics/summary", {}, token);

export const PIPELINE_COLUMNS: { id: PipelineStatus; label: string }[] = [
  { id: "new", label: "New" },
  { id: "drafting", label: "Drafting" },
  { id: "sent", label: "Sent" },
  { id: "negotiating", label: "Negotiating" },
  { id: "won", label: "Won" },
  { id: "lost", label: "Lost" },
  { id: "rejected_tos_violation", label: "ToS Rejected" },
  { id: "rejected_by_sast", label: "SAST Rejected" },
  { id: "pending_payment_verification", label: "Needs Approval" },
  { id: "in_progress", label: "In Progress" },
  { id: "paused_for_budget_extension", label: "Budget Pause" },
  { id: "paused_for_captcha", label: "CAPTCHA Pause" },
  { id: "delivered", label: "Delivered" },
  { id: "paid", label: "Paid" },
  { id: "archived", label: "Archived" },
];

export const logoutApi = () =>
  request<{ message: string }>("/auth/logout", { method: "POST" });
