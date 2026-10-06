import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api, refreshAccessToken, setAccessToken, setSessionLostHandler } from "./api";
import type { Me } from "./types";

type AuthState = {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** True if the user holds any of the given permissions. */
  can: (...codes: string[]) => boolean;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    setSessionLostHandler(() => {
      setAccessToken(null);
      setMe(null);
      navigate("/login", { replace: true });
    });
  }, [navigate]);

  // On first load, try to resume the session from the refresh cookie.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (await refreshAccessToken()) {
          const profile = await api<Me>("/api/auth/me");
          if (!cancelled) setMe(profile);
        }
      } catch {
        // stay logged out
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await api<{ access_token: string }>("/api/auth/login", {
      method: "POST",
      json: { email, password },
    });
    setAccessToken(tokens.access_token);
    setMe(await api<Me>("/api/auth/me"));
  }, []);

  const logout = useCallback(async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      setAccessToken(null);
      setMe(null);
      navigate("/login", { replace: true });
    }
  }, [navigate]);

  const can = useCallback(
    (...codes: string[]) => !!me && codes.some((c) => c in me.permissions),
    [me],
  );

  const value = useMemo(() => ({ me, loading, login, logout, can }), [me, loading, login, logout, can]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
