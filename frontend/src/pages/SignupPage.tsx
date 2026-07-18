import { FormEvent, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../lib/auth";

const ALLOWED_SKILLS = new Set<string>(["python", "javascript", "typescript", "java", "kotlin", "swift", "go", "golang", "rust", "c", "c++", "c#", "php", "ruby", "scala", "elixir", "dart", "r", "sql", "html", "css", "sass", "tailwind", "bootstrap", "react", "react native", "vue", "angular", "svelte", "nextjs", "next.js", "nuxt", "flutter", "electron", "vite", "webpack", "node", "nodejs", "node.js", "express", "nestjs", "fastapi", "django", "flask", "spring", "spring boot", "laravel", "rails", ".net", "asp.net", "postgresql", "postgres", "mysql", "sqlite", "mongodb", "redis", "elasticsearch", "clickhouse", "snowflake", "bigquery", "dynamodb", "cassandra", "docker", "kubernetes", "terraform", "ansible", "linux", "bash", "nginx", "aws", "gcp", "azure", "vercel", "cloudflare", "ci/cd", "github actions", "git", "graphql", "rest", "grpc", "websockets", "oauth", "jwt", "stripe", "kafka", "rabbitmq", "celery", "airflow", "spark", "etl", "dbt", "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch", "opencv", "machine learning", "deep learning", "data science", "data engineering", "nlp", "llm", "openai", "langchain", "rag", "prompt engineering", "pytest", "jest", "cypress", "playwright", "selenium", "tdd", "figma", "ui/ux", "ui/ux design", "web design", "seo", "devops", "security", "penetration testing", "blockchain", "solidity", "web3"]);

const inputClass =
  "w-full rounded-none border border-[#1c3527] bg-[#050e09] px-3 py-2 text-zinc-100 placeholder-zinc-600 outline-none transition-all duration-300 focus:border-[#C5A059] focus:ring-1 focus:ring-[#C5A059]/40";

export default function SignupPage() {
  const { signup, user } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [skills, setSkills] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) {
    return <Navigate to="/" replace />;
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setToast(null);

    const trimmedEmail = email.trim().toLowerCase();

    const skillList = skills
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean);
    const unknown = skillList.filter((s) => !ALLOWED_SKILLS.has(s));
    if (unknown.length > 0) {
      setError(
        `Unrecognized skills: ${unknown.join(", ")}. Enter real skills, comma-separated — e.g. python, fastapi, react.`,
      );
      return;
    }

    setSubmitting(true);
    try {
      await signup(
        name.trim(),
        trimmedEmail,
        password,
        skillList,
        inviteCode.trim() || undefined,
      );
      setToast("Account created — opening your CRM pipeline…");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Signup failed";
      setError(message);
      setToast(message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 py-12 animate-fade-in">
      <div className="border border-[#C5A059]/25 bg-[#0d1b12] p-8 shadow-xl shadow-[#050e09] transition-all duration-500 ease-out">
        {toast && (
          <div
            role="status"
            className={
              error
                ? "mb-4 rounded-none border border-red-900/60 bg-red-950/70 px-3 py-2 text-sm text-red-100"
                : "mb-4 rounded-none border border-[#C5A059]/40 bg-[#050e09] px-3 py-2 text-sm text-[#C5A059]"
            }
          >
            {toast}
          </div>
        )}
        <header className="mb-10">
          <p className="font-display text-3xl font-semibold tracking-tight text-[#C5A059]">
            The Sterling Syndicate
          </p>
          <p className="mt-2 font-sans text-zinc-400">
            Create your account. AI drafts stay drafts until you send them.
          </p>
        </header>

        <form onSubmit={onSubmit} className="space-y-4 font-sans">
          <label className="block">
            <span className="mb-1 block text-sm text-zinc-300">Name</span>
            <input
              type="text"
              required
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={inputClass}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm text-zinc-300">Email</span>
            <input
              type="email"
              required
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputClass}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm text-zinc-300">Password</span>
            <input
              type="password"
              required
              autoComplete="new-password"
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputClass}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm text-zinc-300">
              Skills (comma-separated)
            </span>
            <input
              type="text"
              placeholder="python, fastapi, react"
              value={skills}
              onChange={(e) => setSkills(e.target.value)}
              className={inputClass}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm text-zinc-300">
              Invite code{" "}
              <span className="text-zinc-500">(only if your admin requires one)</span>
            </span>
            <input
              type="text"
              autoComplete="off"
              placeholder="optional"
              value={inviteCode}
              onChange={(e) => setInviteCode(e.target.value)}
              className={inputClass}
            />
          </label>
          {error && (
            <p className="rounded-none border border-red-900/60 bg-red-950/40 px-3 py-2 text-sm text-red-200">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-none bg-[#C5A059] px-4 py-2.5 font-semibold tracking-wide text-[#050e09] transition-all duration-500 hover:bg-[#b08d4a] disabled:opacity-60"
          >
            {submitting ? "Creating account…" : "Create account"}
          </button>
        </form>

        <p className="mt-6 font-sans text-sm text-zinc-400">
          Already have an account?{" "}
          <Link
            to="/login"
            className="text-[#C5A059] transition-colors duration-300 hover:text-[#D4AF37] hover:underline"
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}