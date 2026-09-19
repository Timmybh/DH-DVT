import { FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";

interface PublicConfig {
  google_enabled: boolean;
  google_client_id: string;
  local_enabled: boolean;
}

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (cfg: { client_id: string; callback: (r: { credential: string }) => void }) => void;
          renderButton: (el: HTMLElement, opts: Record<string, unknown>) => void;
        };
      };
    };
  }
}

export default function Login() {
  const { login, loginGoogle, user } = useAuth();
  const navigate = useNavigate();
  const [cfg, setCfg] = useState<PublicConfig>({ google_enabled: false, google_client_id: "", local_enabled: true });
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const googleBtn = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (user) navigate("/", { replace: true });
  }, [user, navigate]);

  useEffect(() => {
    api.get<PublicConfig>("/auth/config").then((r) => setCfg(r.data)).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!cfg.google_enabled || !cfg.google_client_id) return;
    const init = () => {
      if (!window.google || !googleBtn.current) return;
      window.google.accounts.id.initialize({
        client_id: cfg.google_client_id,
        callback: async (res) => {
          try {
            await loginGoogle(res.credential);
            navigate("/");
          } catch (e) {
            setError(errorMessage(e, "Đăng nhập Google thất bại"));
          }
        },
      });
      window.google.accounts.id.renderButton(googleBtn.current, { theme: "outline", size: "large", width: 320, text: "signin_with" });
    };
    if (window.google) {
      init();
      return;
    }
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = init;
    document.head.appendChild(s);
  }, [cfg, loginGoogle, navigate]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username, password);
      navigate("/");
    } catch (err) {
      setError(errorMessage(err, "Đăng nhập thất bại"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-dark via-indigo-900 to-slate-900 px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-10 shadow-2xl">
        <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-xl border-2 border-amber-300 bg-rose-800 text-lg font-bold text-amber-200">DVT</div>
        <h1 className="text-2xl font-bold text-slate-900">Bảng điều hành DVT</h1>
        <p className="mt-1 text-sm text-slate-500">Đăng nhập để xem tình hình điều hành.</p>

        {cfg.google_enabled && (
          <div className="mt-6">
            <div ref={googleBtn} className="flex justify-center" />
            {cfg.local_enabled && <p className="mt-4 text-center text-xs text-slate-400">hoặc dùng tài khoản nội bộ (dự phòng)</p>}
          </div>
        )}

        {cfg.local_enabled ? (
          <form className="mt-5 space-y-4" onSubmit={handleSubmit}>
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-600">Tài khoản hoặc email</label>
              <input
                className="w-full rounded-lg border-0 bg-slate-100 px-4 py-2.5 text-slate-900 focus:outline-none focus:ring-2 focus:ring-brand"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-600">Mật khẩu</label>
              <input
                type="password"
                className="w-full rounded-lg border-0 bg-slate-100 px-4 py-2.5 text-slate-900 focus:outline-none focus:ring-2 focus:ring-brand"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>
            <button type="submit" disabled={loading} className="w-full rounded-lg bg-brand py-2.5 font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-60">
              {loading ? "Đang đăng nhập..." : "Đăng nhập"}
            </button>
          </form>
        ) : (
          !cfg.google_enabled && <p className="mt-5 text-sm text-red-600">Chưa có phương thức đăng nhập khả dụng. Liên hệ quản trị viên.</p>
        )}

        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      </div>
    </div>
  );
}
