import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { applyTokens, DEFAULT_TOKENS, ThemeTokens } from "./palette";

export type ThemeMode = "dark" | "light";
const KEY = "dvt_theme_mode";

interface Ctx {
  mode: ThemeMode;
  toggle: () => void;
  tokens: ThemeTokens;
  version: number;
  setTokens: (t: ThemeTokens, version?: number) => void;
  reload: () => Promise<void>;
}

const ThemeCtx = createContext<Ctx>({ mode: "dark", toggle: () => undefined, tokens: DEFAULT_TOKENS, version: 0, setTokens: () => undefined, reload: async () => undefined });

const readMode = (): ThemeMode => {
  try {
    return localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
};

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(readMode);
  const [tokens, setTokensState] = useState<ThemeTokens>(DEFAULT_TOKENS);
  const [version, setVersion] = useState(0);

  const setTokens = useCallback((t: ThemeTokens, v?: number) => {
    applyTokens(t);
    setTokensState(t);
    if (v !== undefined) setVersion(v);
  }, []);
  const reload = useCallback(async () => {
    try {
      const r = await api.get<{ tokens: ThemeTokens; version: number }>("/theme");
      setTokens(r.data.tokens, r.data.version);
    } catch {
      /* dùng token mặc định khi chưa tải được */
    }
  }, [setTokens]);
  useEffect(() => {
    applyTokens(DEFAULT_TOKENS);
    reload();
  }, [reload]);

  const toggle = useCallback(() => {
    setMode((m) => {
      const next = m === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(KEY, next);
      } catch {
        /* bỏ qua */
      }
      return next;
    });
  }, []);

  const value = useMemo(() => ({ mode, toggle, tokens, version, setTokens, reload }), [mode, toggle, tokens, version, setTokens, reload]);
  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);
