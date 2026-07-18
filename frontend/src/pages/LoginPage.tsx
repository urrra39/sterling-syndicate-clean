import { FormEvent, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../lib/auth";

const inputClass =
  "w-full rounded-none border border-[#1c3527] bg-[#050e09] px-3 py-2 text-zinc-100 placeholder-zinc-600 outline-none transition-all duration-300 focus:border-[#C5A059] focus:ring-1 focus:ring-[#C5A059]/40";

export default function LoginPage() {
  const { login, user } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      setToast("Signed in — opening pipeline…");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Login failed";
      setError(message);
      setToast(message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 animate-fade-in">
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
            Sign in to your elite executive agency.
          </p>
        </header>

        <form onSubmit={onSubmit} className="space-y-4 font-sans">
          <label className="block">
            <span className="mb-1 block text-sm text-zinc-300">Email</span>
            <input
              type="email"
              required
              autoComplete="email"
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
              autoComplete="current-password"
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
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
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-4 font-sans text-sm text-zinc-400">
          <Link
            to="/forgot-password"
            className="text-[#C5A059] transition-colors duration-300 hover:text-[#D4AF37] hover:underline"
          >
            Forgot your password?
          </Link>
        </p>

        <p className="mt-6 font-sans text-sm text-zinc-400">
          No account?{" "}
          <Link
            to="/signup"
            className="text-[#C5A059] transition-colors duration-300 hover:text-[#D4AF37] hover:underline"
          >
            Create one
          </Link>
        </p>
      </div>
    </div>
  );
}