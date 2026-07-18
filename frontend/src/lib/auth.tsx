import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import * as api from "./api";
import type { UserPublic } from "./api";

type AuthContextValue = {
  /**
   * Session sentinel only — the real JWT lives in an HttpOnly cookie and is
   * never readable from JS. Non-null means "authenticated" (value is always
   * the literal `"cookie"` after a successful hydrate/login).
   */
  token: string | null;
  user: UserPublic | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (
    name: string,
    email: string,
    password: string,
    skills?: string[],
    inviteCode?: string,
  ) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const COOKIE_SENTINEL = "cookie";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<UserPublic | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function hydrate() {
      try {
        // Cookie is sent automatically via credentials:"include"
        const me = await api.fetchMe(COOKIE_SENTINEL);
        if (!cancelled) {
          setUser(me);
          setToken(COOKIE_SENTINEL);
        }
      } catch {
        if (!cancelled) {
          setUser(null);
          setToken(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void hydrate();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.login({ email, password });
    // Server sets HttpOnly cookie; body.access_token is intentionally empty.
    setToken(COOKIE_SENTINEL);
    setUser(res.user);
  }, []);

  const signup = useCallback(
    async (
      name: string,
      email: string,
      password: string,
      skills: string[] = [],
      inviteCode?: string,
    ) => {
      const res = await api.signup({
        name,
        email,
        password,
        skills,
        invite_code: inviteCode || undefined,
      });
      setToken(COOKIE_SENTINEL);
      setUser(res.user);
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await api.logoutApi();
    } catch {
      // Best-effort; clear local state regardless
    }
    setToken(null);
    setUser(null);
  }, []);

  // A 401 on any endpoint (expired token mid-session) dispatches this event
  // from api.request(); tear down the session so ProtectedRoute redirects.
  useEffect(() => {
    const onUnauthorized = () => {
      setToken(null);
      setUser(null);
    };
    window.addEventListener("sterling:unauthorized", onUnauthorized);
    return () => window.removeEventListener("sterling:unauthorized", onUnauthorized);
  }, []);

  const value = useMemo(
    () => ({ token, user, loading, login, signup, logout }),
    [token, user, loading, login, signup, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
