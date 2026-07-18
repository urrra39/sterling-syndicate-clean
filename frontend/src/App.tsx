import type { ReactNode } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import LoginPage from "./pages/LoginPage";
import SignupPage from "./pages/SignupPage";
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";
import BoardPage from "./pages/BoardPage";
import LeadDetailPage from "./pages/LeadDetailPage";
import AnalyticsPage from "./pages/AnalyticsPage";

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center font-sans text-zinc-300">
        Loading…
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function Shell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const loc = useLocation();
  const link = (to: string, label: string) => (
    <Link
      to={to}
      className={
        loc.pathname === to || (to !== "/" && loc.pathname.startsWith(to))
          ? "border-l-2 border-[#C5A059] pl-2 text-[#C5A059] transition-colors duration-500"
          : "border-l-2 border-transparent pl-2 text-zinc-400 transition-colors duration-500 hover:text-[#C5A059]"
      }
    >
      {label}
    </Link>
  );

  return (
    <div className="min-h-screen font-sans">
      <header className="border-b border-[#C5A059]/15 bg-[#0d1b12]/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-4">
          <div className="flex items-center gap-8">
            <Link
              to="/"
              className="font-display text-xl font-semibold tracking-wide text-[#C5A059]"
            >
              The Sterling Syndicate
            </Link>
            <nav className="flex gap-5 text-sm">
              {link("/", "Pipeline")}
              {link("/analytics", "Analytics")}
            </nav>
          </div>
          <div className="flex items-center gap-4 text-sm text-zinc-400">
            <span>{user?.name}</span>
            <button
              type="button"
              onClick={logout}
              className="rounded-none border border-[#C5A059]/30 px-2 py-1 text-[#C5A059] transition-all duration-500 ease-out hover:border-[#C5A059]/60 hover:bg-[#112419] hover:text-[#D4AF37]"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6 animate-fade-in">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Shell>
                <BoardPage />
              </Shell>
            </ProtectedRoute>
          }
        />
        <Route
          path="/leads/:id"
          element={
            <ProtectedRoute>
              <Shell>
                <LeadDetailPage />
              </Shell>
            </ProtectedRoute>
          }
        />
        <Route
          path="/analytics"
          element={
            <ProtectedRoute>
              <Shell>
                <AnalyticsPage />
              </Shell>
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}