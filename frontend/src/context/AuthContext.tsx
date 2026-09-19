import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, AuthUser } from "../api/client";

interface AuthContextValue {
  user: AuthUser | null;
  ready: boolean;
  can: (permission: string) => boolean;
  login: (username: string, password: string) => Promise<void>;
  loginGoogle: (credential: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);

  const clear = useCallback(() => {
    localStorage.removeItem("dvt_token");
    setUser(null);
  }, []);

  useEffect(() => {
    const token = localStorage.getItem("dvt_token");
    if (!token) {
      setReady(true);
      return;
    }
    api
      .get<AuthUser>("/auth/me")
      .then((res) => setUser(res.data))
      .catch(clear)
      .finally(() => setReady(true));
  }, [clear]);

  useEffect(() => {
    window.addEventListener("dvt-unauthorized", clear);
    return () => window.removeEventListener("dvt-unauthorized", clear);
  }, [clear]);

  const accept = (data: { access_token: string; user: AuthUser }) => {
    localStorage.setItem("dvt_token", data.access_token);
    setUser(data.user);
  };

  const value: AuthContextValue = {
    user,
    ready,
    can: (p) => !!user?.permissions.includes(p),
    login: async (username, password) => accept((await api.post("/auth/login", { username, password })).data),
    loginGoogle: async (credential) => accept((await api.post("/auth/google", { credential })).data),
    logout: () => {
      api.post("/auth/logout").catch(() => undefined);
      clear();
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
