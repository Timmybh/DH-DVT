import { createContext, ReactNode, useContext, useState } from "react";
import { api } from "../api/client";

interface AuthUser {
  full_name: string;
  role: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => {
    const raw = localStorage.getItem("dhdvt_user");
    return raw ? JSON.parse(raw) : null;
  });

  async function login(username: string, password: string) {
    const { data } = await api.post("/auth/login", { username, password });
    localStorage.setItem("dhdvt_token", data.access_token);
    const authUser = { full_name: data.full_name, role: data.role };
    localStorage.setItem("dhdvt_user", JSON.stringify(authUser));
    setUser(authUser);
  }

  function logout() {
    localStorage.removeItem("dhdvt_token");
    localStorage.removeItem("dhdvt_user");
    setUser(null);
  }

  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
