import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  authorizeBudgetExtension,
  ApiError,
  claimPayment,
  confirmPayment,
  createContract,
  draftProposal,
  getContract,
  getLead,
  ingestGithubPortfolio,
  listConversations,
  listProposals,
  markPaid,
  markProposalSent,
  runExecution,
  safeExternalUrl,
  setProposalOutcome,
  suggestReplies,
  updateDeliverable,
  type Contract,
  type Conversation,
  type ExecutionResult,
  type Lead,
  type Proposal,
  type ReplySuggestion,
} from "../lib/api";
import { useAuth } from "../lib/auth";

export default function LeadDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { token } = useAuth();
  const [lead, setLead] = useState<Lead | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [contract, setContract] = useState<Contract | null>(null);
  const [suggestions, setSuggestions] = useState<ReplySuggestion[]>([]);
  const [incoming, setIncoming] = useState("");
  const [tone, setTone] = useState("confident");
  const [error, setError] = useState<string | null>(null);
  const [scope, setScope] = useState("");
  const [price, setPrice] = useState("");
  const [deliverable, setDeliverable] = useState("");
  const [ghUser, setGhUser] = useState("");
  const [clientName, setClientName] = useState("");
  const [execBusy, setExecBusy] = useState(false);
  const [execResult, setExecResult] = useState<ExecutionResult | null>(null);
  const [taskPrompt, setTaskPrompt] = useState("");
  const [mfaCode, setMfaCode] = useState("");

  const paymentLocked = !!contract && !contract.is_payment_verified;
  const budgetPaused =
    !!contract &&
    (contract.status === "paused_for_budget_extension" ||
      lead?.pipeline_status === "paused_for_budget_extension");
  const captchaPaused = lead?.pipeline_status === "paused_for_captcha";
  const sastRejected =
    lead?.pipeline_status === "rejected_by_sast" ||
    contract?.qa_status === "rejected_by_sast";

  const load = useCallback(async () => {
    if (!token || !id) return;
    try {
      const [l, p, c] = await Promise.all([
        getLead(token, id),
        listProposals(token, id),
        listConversations(token, id),
      ]);
      setLead(l);
      setProposals(p);
      setConversations(c);
      try {
        setContract(await getContract(token, id));
      } catch (e) {
        // 404 is the only expected miss (lead has no contract yet). Anything else
        // (transient 500/401/network) must surface — don't fake "no contract",
        // which would show the create-contract form for a lead that has one.
        if (e instanceof ApiError && e.status === 404) {
          setContract(null);
        } else {
          throw e;
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed");
    }
  }, [token, id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onDraft() {
    if (!token || !id) return;
    try {
      await draftProposal(token, id, tone);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Draft failed");
    }
  }

  async function onSuggest(e: FormEvent) {
    e.preventDefault();
    if (!token || !id) return;
    try {
      const s = await suggestReplies(token, id, incoming);
      setSuggestions(s);
      setIncoming("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Suggest failed");
    }
  }

  async function onContract(e: FormEvent) {
    e.preventDefault();
    if (!token || !id) return;
    try {
      await createContract(token, id, {
        agreed_scope: scope,
        agreed_price: Number(price),
        client_display_name: clientName.trim() || undefined,
        deliverables: deliverable
          ? [{ description: deliverable, checklist: ["Kickoff", "Draft", "Final"] }]
          : [],
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Contract failed");
    }
  }

  if (!lead) {
    return <p className="text-zinc-400">{error ?? "Loading lead…"}</p>;
  }

  const sourceHref = safeExternalUrl(lead.url);

  async function onConfirmPayment() {
    if (!token || !lead) return;
    try {
      await confirmPayment(token, lead.id, mfaCode.trim() || undefined);
      setMfaCode("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Confirm payment failed");
    }
  }

  return (
    <div className="space-y-8 animate-fade-in">
      <div>
        <Link to="/" className="text-sm text-[#C5A059] transition-colors duration-300 hover:text-[#D4AF37] hover:underline">
          ← Pipeline
        </Link>
        <h1 className="mt-2 font-display text-2xl font-semibold text-zinc-100">
          {lead.title}
        </h1>
        <p className="mt-1 text-sm text-zinc-400">
          {lead.source} · {lead.pipeline_status}
          {lead.match_score != null && <> · match {(lead.match_score * 100).toFixed(0)}%</>}
          {sourceHref && (
            <>
              {" · "}
              <a href={sourceHref} target="_blank" rel="noopener noreferrer" className="text-[#C5A059] transition-colors duration-300 hover:text-[#D4AF37]">
                source link
              </a>
            </>
          )}
        </p>
      </div>

      {error && (
        <p className="rounded-none border border-red-900/50 bg-red-950/30 px-3 py-2 text-sm text-red-200">
          {error}
        </p>
      )}

      {paymentLocked && token && (
        <div className="rounded-none border-2 border-[#D4AF37] bg-[#112419] p-4 shadow-[0_0_24px_rgba(197,160,89,0.25)]">
          <p className="font-display text-xs font-bold uppercase tracking-widest text-[#D4AF37]">
            Needs Approval · Payment Kill Switch Active
          </p>
          <p className="mt-2 text-sm text-zinc-200">
            Client{" "}
            <span className="font-semibold">
              {contract?.client_display_name || lead.title || "Client"}
            </span>{" "}
            initiated a payment of{" "}
            <span className="font-semibold">
              {contract?.currency} {contract?.agreed_price}
            </span>
            . All Writer / Negotiator / deliverable actions are frozen until you verify
            funds in your account.
          </p>
          <div className="mt-4 flex flex-wrap items-end gap-3">
            <label className="block text-xs text-zinc-400">
              Step-up MFA code (if enabled)
              <input
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={12}
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value)}
                placeholder="6-digit code"
                className="mt-1 block w-40 rounded-none border border-[#1c3527] bg-[#050e09] px-2 py-1.5 text-sm text-zinc-100 focus:border-[#C5A059]"
              />
            </label>
            <button
              type="button"
              onClick={() => void onConfirmPayment()}
              className="rounded-none bg-[#C5A059] px-4 py-2 text-sm font-bold text-[#050e09] transition-all duration-500 hover:bg-[#D4AF37]"
            >
              Confirm Payment Received
            </button>
          </div>
        </div>
      )}

      {budgetPaused && token && contract && (
        <div className="rounded-none border-2 border-red-900/80 bg-[#112419] p-4">
          <p className="font-display text-xs font-bold uppercase tracking-widest text-red-300">
            Profit Guard · Budget Pause
          </p>
          <p className="mt-2 text-sm text-zinc-200">
            API budget depleted for this project ({contract.completeness_pct.toFixed(0)}%
            complete). Spent ${contract.cumulative_api_cost.toFixed(2)} / $
            {contract.max_api_budget.toFixed(2)}. Authorize +5% or review the draft
            manually — nothing was delivered to the client.
          </p>
          <button
            type="button"
            onClick={() =>
              void authorizeBudgetExtension(token, lead.id)
                .then(load)
                .catch((e: Error) => setError(e.message))
            }
            className="mt-4 rounded-none bg-[#C5A059] px-4 py-2 text-sm font-bold text-[#050e09] transition-all duration-500 hover:bg-[#b08d4a]"
          >
            Authorize +5% Budget Extension
          </button>
        </div>
      )}

      {captchaPaused && (
        <div className="rounded-none border-2 border-red-900/80 bg-[#112419] p-4">
          <p className="font-display text-xs font-bold uppercase tracking-widest text-red-300">
            CAPTCHA / MFA · Intervention Required
          </p>
          <p className="mt-2 text-sm text-zinc-200">
            Automation paused for a CAPTCHA or MFA challenge. Solve it in a headed
            browser, then resume via{" "}
            <code className="text-xs">POST /browser/captcha/&#123;pause_id&#125;/resume</code>.
            Marketplace login automation remains disabled.
          </p>
        </div>
      )}

      {sastRejected && (
        <div className="rounded-none border-2 border-[#b08d4a]/70 bg-[#112419] p-4">
          <p className="font-display text-xs font-bold uppercase tracking-widest text-[#b08d4a]">
            SAST Rejected · Secure Rewrite Required
          </p>
          <p className="mt-2 text-sm text-zinc-200">
            Pre-delivery security scan found vulnerable patterns (possible poisoned RAG).
            Draft is not ready_for_delivery until SAST passes. Re-run Execution Agent to
            force a secure rewrite.
          </p>
        </div>
      )}

      <section className="grid gap-6 lg:grid-cols-2">
        <div className="border border-[#1c3527] bg-[#112419] p-4 transition-all duration-500 ease-out hover:border-[#C5A059]/40">
          <h2 className="font-display text-sm font-semibold uppercase tracking-wide text-[#C5A059]/80">
            Original post
          </h2>
          <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap font-sans text-sm text-zinc-200">
            {lead.raw_text}
          </pre>
        </div>

        <div className="space-y-4 border border-[#1c3527] bg-[#112419] p-4 transition-all duration-500 ease-out hover:border-[#C5A059]/40">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-display text-sm font-semibold uppercase tracking-wide text-[#C5A059]/80">
              Proposal drafts
            </h2>
            <div className="flex gap-2">
              <select
                value={tone}
                onChange={(e) => setTone(e.target.value)}
                className="rounded-none border border-[#1c3527] bg-[#050e09] px-2 py-1 text-sm text-zinc-100 transition-all duration-300 focus:border-[#C5A059]"
              >
                <option value="confident">Confident</option>
                <option value="friendly">Friendly</option>
                <option value="concise">Concise</option>
              </select>
              <button
                type="button"
                disabled={paymentLocked}
                title={
                  paymentLocked
                    ? "Blocked until payment is confirmed"
                    : undefined
                }
                onClick={() => void onDraft()}
                className="rounded-none bg-[#C5A059] px-3 py-1 text-sm font-semibold text-[#050e09] transition-all duration-500 hover:bg-[#b08d4a] disabled:cursor-not-allowed disabled:opacity-40"
              >
                Generate draft
              </button>
            </div>
          </div>
          {proposals.length === 0 && (
            <p className="text-sm text-zinc-500">No drafts yet.</p>
          )}
          {proposals.map((p) => (
            <article key={p.id} className="border border-[#1c3527] bg-[#0d1b12] p-3 transition-all duration-500 ease-out hover:border-[#C5A059]/40">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-zinc-500">
                <span className="border border-[#C5A059]/30 bg-[#C5A059]/10 px-1.5 py-0.5 text-[#C5A059]">
                  {p.generated_by}
                </span>
                <span>{p.status}</span>
                <span>{p.tone}</span>
                {p.recommended_bid != null && (
                  <span className="text-[#C5A059] transition-colors duration-300 hover:text-[#D4AF37]">bid ${p.recommended_bid}</span>
                )}
                {p.outcome && <span>outcome: {p.outcome}</span>}
              </div>
              {p.rag_citations && (
                <p className="mb-2 text-xs text-zinc-500">RAG: {p.rag_citations}</p>
              )}
              <pre className="whitespace-pre-wrap font-sans text-sm text-zinc-200">
                {p.draft_text}
              </pre>
              <div className="mt-3 flex flex-wrap gap-2">
                {p.status === "draft" && token && (
                  <button
                    type="button"
                    className="rounded-none border border-[#1c3527] px-2 py-1 text-xs text-zinc-300 transition-all duration-500 hover:border-[#C5A059]/60 hover:text-[#C5A059]"
                    onClick={() =>
                      void markProposalSent(token, p.id)
                        .then(load)
                        .catch((e: Error) => setError(e.message))
                    }
                  >
                    I sent this myself
                  </button>
                )}
                {token && !p.outcome && (
                  <>
                    <button
                      type="button"
                      className="rounded-none border border-[#C5A059]/50 px-2 py-1 text-xs text-[#C5A059] transition-all duration-500 hover:border-[#C5A059]"
                      onClick={() =>
                        void setProposalOutcome(token, p.id, "accepted")
                          .then(load)
                          .catch((e: Error) => setError(e.message))
                      }
                    >
                      Mark accepted
                    </button>
                    <button
                      type="button"
                      className="rounded-none border border-red-900 px-2 py-1 text-xs text-red-300 transition-all duration-500 hover:border-red-700"
                      onClick={() =>
                        void setProposalOutcome(token, p.id, "rejected")
                          .then(load)
                          .catch((e: Error) => setError(e.message))
                      }
                    >
                      Mark rejected (reflect)
                    </button>
                  </>
                )}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="border border-[#1c3527] bg-[#112419] p-4 transition-all duration-500 ease-out hover:border-[#C5A059]/40">
        <h2 className="font-display text-sm font-semibold uppercase tracking-wide text-[#C5A059]/80">
          Portfolio RAG (GitHub)
        </h2>
        <form
          className="mt-3 flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!token || !ghUser.trim()) return;
            void ingestGithubPortfolio(token, ghUser.trim())
              .then((r) => {
                setError(null);
                alert(`Ingested ${r.upserted} docs into Chroma`);
              })
              .catch((err: Error) => setError(err.message));
          }}
        >
          <input
            value={ghUser}
            onChange={(e) => setGhUser(e.target.value)}
            placeholder="GitHub username"
            className="rounded-none border border-[#1c3527] bg-[#050e09] px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition-all duration-300 focus:border-[#C5A059] focus:ring-1 focus:ring-[#C5A059]/40"
          />
          <button
            type="submit"
            className="rounded-none bg-[#C5A059] px-3 py-2 text-sm font-semibold text-[#050e09] transition-all duration-500 hover:bg-[#b08d4a]"
          >
            Ingest READMEs
          </button>
        </form>
      </section>

      <section className="border border-[#1c3527] bg-[#112419] p-4 transition-all duration-500 ease-out hover:border-[#C5A059]/40">
        <h2 className="font-display text-sm font-semibold uppercase tracking-wide text-[#C5A059]/80">
          Negotiation copilot
        </h2>
        <form onSubmit={onSuggest} className="mt-3 space-y-2">
          <textarea
            required
            rows={3}
            value={incoming}
            onChange={(e) => setIncoming(e.target.value)}
            placeholder="Paste the client's incoming message…"
            className="w-full rounded-none border border-[#1c3527] bg-[#050e09] px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition-all duration-300 focus:border-[#C5A059] focus:ring-1 focus:ring-[#C5A059]/40"
          />
          <button
            type="submit"
            disabled={paymentLocked}
            title={
              paymentLocked ? "Blocked until payment is confirmed" : undefined
            }
            className="rounded-none bg-[#C5A059] px-3 py-2 text-sm font-semibold text-[#050e09] transition-all duration-500 hover:bg-[#b08d4a] disabled:cursor-not-allowed disabled:opacity-40"
          >
            Suggest replies
          </button>
          {paymentLocked && (
            <p className="text-xs text-[#C5A059]">
              Negotiator frozen — confirm payment received to unlock.
            </p>
          )}
        </form>
        {suggestions.length > 0 && (
          <div className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {suggestions.map((s) => (
              <div
                key={s.label}
                className={
                  s.scope_creep_detected
                    ? "border-2 border-[#C5A059]/80 bg-[#C5A059]/10 p-3 transition-all duration-500 ease-out"
                    : "border border-[#1c3527] bg-[#0d1b12] p-3 transition-all duration-500 ease-out hover:border-[#C5A059]/40"
                }
              >
                <p
                  className={
                    s.scope_creep_detected
                      ? "text-xs font-semibold text-[#D4AF37]"
                      : "text-xs font-semibold text-[#C5A059]"
                  }
                >
                  {s.scope_creep_detected ? "🛡️ " : ""}
                  {s.label}
                </p>
                <p className="mt-1 text-xs text-[#C5A059]/80">
                  ai_generated · LLM draft
                </p>
                {s.scope_creep_detected && s.out_of_scope_summary && (
                  <p className="mt-1 text-xs text-zinc-300">
                    Out of scope: {s.out_of_scope_summary}
                  </p>
                )}
                <pre className="mt-2 whitespace-pre-wrap font-sans text-sm text-zinc-200">
                  {s.body}
                </pre>
              </div>
            ))}
          </div>
        )}
        <ul className="mt-4 space-y-2">
          {conversations.map((c) => (
            <li key={c.id} className="border border-[#1c3527] bg-[#0d1b12] px-3 py-2 text-sm transition-all duration-500 ease-out hover:border-[#C5A059]/30">
              <span className="text-xs text-zinc-500">
                {c.direction} · {c.generated_by}
                {c.label ? ` · ${c.label}` : ""}
              </span>
              <p className="mt-1 text-zinc-200">{c.body}</p>
            </li>
          ))}
        </ul>
      </section>

      {contract?.is_payment_verified && (
        <section className="border border-[#1c3527] bg-[#112419] p-4 transition-all duration-500 ease-out hover:border-[#C5A059]/40">
          <h2 className="font-display text-sm font-semibold uppercase tracking-wide text-[#C5A059]/80">
            Execution Agent · Profit Guard
          </h2>
          <p className="mt-2 text-xs text-zinc-500">
            Effort: {contract.effort_level} · Budget ${contract.cumulative_api_cost.toFixed(2)} / $
            {contract.max_api_budget.toFixed(2)} · QA: {contract.qa_status} ·{" "}
            {contract.completeness_pct.toFixed(0)}% complete
          </p>
          <div className="mt-2 h-2 overflow-hidden bg-[#1c3527]">
            <div
              className={
                budgetPaused
                  ? "h-full bg-red-800"
                  : contract.cumulative_api_cost / Math.max(contract.max_api_budget, 0.01) >= 0.9
                    ? "h-full bg-[#D4AF37]"
                    : "h-full bg-[#C5A059]"
              }
              style={{
                width: `${Math.min(
                  100,
                  (contract.cumulative_api_cost / Math.max(contract.max_api_budget, 0.01)) * 100,
                )}%`,
              }}
            />
          </div>
          <textarea
            rows={2}
            value={taskPrompt}
            onChange={(e) => setTaskPrompt(e.target.value)}
            placeholder="Optional task focus for Execution_Agent…"
            disabled={paymentLocked || budgetPaused}
            className="mt-3 w-full rounded-none border border-[#1c3527] bg-[#050e09] px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition-all duration-300 focus:border-[#C5A059] focus:ring-1 focus:ring-[#C5A059]/40 disabled:opacity-40"
          />
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={paymentLocked || budgetPaused || execBusy || !token}
              onClick={() => {
                if (!token) return;
                setExecBusy(true);
                void runExecution(token, lead.id, {
                  task_prompt: taskPrompt,
                  run_qa: true,
                })
                  .then((r) => {
                    setExecResult(r);
                    return load();
                  })
                  .catch((e: Error) => setError(e.message))
                  .finally(() => setExecBusy(false));
              }}
              className="rounded-none bg-[#C5A059] px-3 py-2 text-sm font-semibold text-[#050e09] transition-all duration-500 hover:bg-[#b08d4a] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {execBusy ? "Running…" : "Run Execution + QA"}
            </button>
            {budgetPaused && token && (
              <button
                type="button"
                onClick={() =>
                  void authorizeBudgetExtension(token, lead.id)
                    .then(load)
                    .catch((e: Error) => setError(e.message))
                }
                className="rounded-none border border-red-300/60 px-3 py-2 text-sm text-red-300 transition-all duration-500 hover:border-red-200"
              >
                Authorize +5%
              </button>
            )}
          </div>
          {(execResult?.draft || contract.execution_draft) && (
            <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap rounded-none border border-[#1c3527] bg-[#050e09] p-3 font-mono text-xs text-zinc-300">
              {execResult?.draft || contract.execution_draft}
            </pre>
          )}
          {execResult?.message && (
            <p className="mt-2 text-xs text-zinc-400">{execResult.message}</p>
          )}
          {execResult?.qa && !execResult.qa.sast_passed && (
            <pre className="mt-2 max-h-40 overflow-auto rounded-none border border-[#b08d4a]/60 bg-[#0d1b12] p-2 text-xs text-[#b08d4a]">
              {execResult.qa.sast_log || execResult.qa.issues}
            </pre>
          )}
          {execResult?.ready_for_delivery && (
            <p className="mt-2 text-xs font-semibold text-[#C5A059]">
              SAST + QA passed — ready_for_delivery (human still delivers).
            </p>
          )}
        </section>
      )}

      <section className="border border-[#1c3527] bg-[#112419] p-4 transition-all duration-500 ease-out hover:border-[#C5A059]/40">
        <h2 className="font-display text-sm font-semibold uppercase tracking-wide text-[#C5A059]/80">
          Contract & deliverables
        </h2>
        {!contract ? (
          <form onSubmit={onContract} className="mt-3 grid max-w-lg gap-2">
            <textarea
              required
              rows={3}
              placeholder="Agreed scope"
              value={scope}
              onChange={(e) => setScope(e.target.value)}
              className="rounded-none border border-[#1c3527] bg-[#050e09] px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition-all duration-300 focus:border-[#C5A059] focus:ring-1 focus:ring-[#C5A059]/40"
            />
            <input
              required
              type="number"
              min={1}
              step="0.01"
              placeholder="Agreed price"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              className="rounded-none border border-[#1c3527] bg-[#050e09] px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition-all duration-300 focus:border-[#C5A059] focus:ring-1 focus:ring-[#C5A059]/40"
            />
            <input
              placeholder="Client display name (for payment alert)"
              value={clientName}
              onChange={(e) => setClientName(e.target.value)}
              className="rounded-none border border-[#1c3527] bg-[#050e09] px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition-all duration-300 focus:border-[#C5A059] focus:ring-1 focus:ring-[#C5A059]/40"
            />
            <input
              placeholder="First deliverable description"
              value={deliverable}
              onChange={(e) => setDeliverable(e.target.value)}
              className="rounded-none border border-[#1c3527] bg-[#050e09] px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition-all duration-300 focus:border-[#C5A059] focus:ring-1 focus:ring-[#C5A059]/40"
            />
            <button
              type="submit"
              className="rounded-none bg-[#C5A059] px-3 py-2 text-sm font-semibold text-[#050e09] transition-all duration-500 hover:bg-[#b08d4a]"
            >
              Log won deal (locks until payment verified)
            </button>
          </form>
        ) : (
          <div className="mt-3 space-y-3">
            <p className="text-sm text-zinc-300">
              {contract.currency} {contract.agreed_price} · {contract.status}
              {contract.is_payment_verified ? (
                <span className="ml-2 text-[#C5A059]">· payment verified</span>
              ) : (
                <span className="ml-2 font-semibold text-[#D4AF37]">
                  · awaiting your verification
                </span>
              )}
            </p>
            {contract.client_display_name && (
              <p className="text-xs text-zinc-500">
                Client: {contract.client_display_name}
              </p>
            )}
            <pre className="whitespace-pre-wrap font-sans text-sm text-zinc-200">
              {contract.agreed_scope}
            </pre>
            <ul className="space-y-2">
              {contract.deliverables.map((d) => (
                <li
                  key={d.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-none border border-[#1c3527] bg-[#0d1b12] px-3 py-2 text-sm transition-all duration-500 ease-out hover:border-[#C5A059]/30"
                >
                  <div>
                    <p>{d.description}</p>
                    <p className="text-xs text-zinc-500">{d.checklist.join(" · ")}</p>
                  </div>
                  <select
                    value={d.status}
                    disabled={paymentLocked}
                    title={
                      paymentLocked
                        ? "Blocked until payment is confirmed"
                        : undefined
                    }
                    onChange={(e) => {
                      if (!token) return;
                      void updateDeliverable(token, d.id, { status: e.target.value })
                        .then(load)
                        .catch((err: Error) => setError(err.message));
                    }}
                    className="rounded-none border border-[#1c3527] bg-[#050e09] px-2 py-1 text-xs text-zinc-100 transition-all duration-300 focus:border-[#C5A059] disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <option value="pending">pending</option>
                    <option value="in_progress">in_progress</option>
                    <option value="delivered">delivered</option>
                  </select>
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap gap-2">
              {paymentLocked && token && (
                <div className="flex flex-wrap items-end gap-2">
                  <label className="block text-xs text-zinc-400">
                    MFA
                    <input
                      type="text"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      maxLength={12}
                      value={mfaCode}
                      onChange={(e) => setMfaCode(e.target.value)}
                      placeholder="code"
                      className="mt-1 block w-28 rounded-none border border-[#1c3527] bg-[#050e09] px-2 py-1 text-xs text-zinc-100 focus:border-[#C5A059]"
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => void onConfirmPayment()}
                    className="rounded-none bg-[#C5A059] px-3 py-1 text-sm font-bold text-[#050e09] transition-all duration-500 hover:bg-[#D4AF37]"
                  >
                    Confirm Payment Received
                  </button>
                </div>
              )}
              {!paymentLocked &&
                contract.is_payment_verified &&
                lead.pipeline_status !== "paid" &&
                token && (
                  <button
                    type="button"
                    onClick={() =>
                      void claimPayment(token, lead.id, {
                        client_display_name:
                          contract.client_display_name || undefined,
                      })
                        .then(load)
                        .catch((e: Error) => setError(e.message))
                    }
                    className="rounded-none border border-[#C5A059] px-3 py-1 text-sm text-[#C5A059] transition-all duration-500 hover:border-[#D4AF37]"
                  >
                    Client claimed payment (re-lock)
                  </button>
                )}
              {lead.pipeline_status !== "paid" &&
                contract.is_payment_verified &&
                token && (
                  <button
                    type="button"
                    onClick={() =>
                      void markPaid(token, lead.id)
                        .then(load)
                        .catch((e: Error) => setError(e.message))
                    }
                    className="rounded-none border border-[#C5A059]/60 px-3 py-1 text-sm text-[#C5A059] transition-all duration-500 hover:border-[#C5A059]"
                  >
                    Mark paid
                  </button>
                )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
