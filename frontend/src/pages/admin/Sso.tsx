import { useEffect, useState } from "react";
import { api, errorMessage } from "../../api/client";

interface Cfg {
  google_enabled: boolean;
  google_client_id: string;
  allowed_domains: string;
  redirect_uri: string;
  local_fallback_enabled: boolean;
}

export default function Sso() {
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    api.get<Cfg>("/admin/sso").then((r) => setCfg(r.data)).catch((e) => setMsg({ ok: false, text: errorMessage(e) }));
  }, []);

  async function save() {
    if (!cfg) return;
    try {
      await api.put("/admin/sso", cfg);
      setMsg({ ok: true, text: "Đã lưu cấu hình đăng nhập." });
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    }
  }
  if (!cfg) return <p className="text-sm text-slate-500">Đang tải...</p>;
  const field = "mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm";

  return (
    <div className="max-w-2xl space-y-5">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Cấu hình đăng nhập</h1>
        <p className="text-sm text-slate-500">Google SSO là phương thức chính. Tài khoản nội bộ chỉ là dự phòng tạm thời/khẩn cấp và mọi lượt đăng nhập đều được audit.</p>
      </div>
      {msg && <div className={`rounded-xl border p-3 text-sm ${msg.ok ? "border-green-200 bg-green-50 text-green-800" : "border-red-200 bg-red-50 text-red-700"}`}>{msg.text}</div>}

      <div className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <label className="flex items-center gap-2 text-sm font-semibold text-slate-800">
          <input type="checkbox" checked={cfg.google_enabled} onChange={(e) => setCfg({ ...cfg, google_enabled: e.target.checked })} /> Bật Google SSO
        </label>
        <label className="block text-xs font-medium text-slate-500">Google Client ID
          <input className={field} value={cfg.google_client_id} onChange={(e) => setCfg({ ...cfg, google_client_id: e.target.value })} placeholder="xxxxxxxx.apps.googleusercontent.com" />
        </label>
        <label className="block text-xs font-medium text-slate-500">Domain email được phép (phân tách bằng dấu phẩy, để trống = mọi domain)
          <input className={field} value={cfg.allowed_domains} onChange={(e) => setCfg({ ...cfg, allowed_domains: e.target.value })} placeholder="dongtien.com.vn" />
        </label>
        <label className="block text-xs font-medium text-slate-500">Redirect URI (ghi nhận để đối chiếu với Google Cloud Console)
          <input className={field} value={cfg.redirect_uri} onChange={(e) => setCfg({ ...cfg, redirect_uri: e.target.value })} placeholder="https://dvt.example.com" />
        </label>
        <p className="text-xs text-slate-400">Người dùng đăng nhập Google phải có sẵn tài khoản (đúng email) trong mục Người dùng; hệ thống không tự tạo tài khoản.</p>
      </div>

      <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5">
        <label className="flex items-center gap-2 text-sm font-semibold text-amber-900">
          <input type="checkbox" checked={cfg.local_fallback_enabled} onChange={(e) => setCfg({ ...cfg, local_fallback_enabled: e.target.checked })} /> Cho phép đăng nhập tài khoản nội bộ (dự phòng)
        </label>
        <p className="mt-1 text-xs text-amber-700">Chỉ áp dụng cho người dùng được đánh dấu "Cho phép đăng nhập nội bộ". Tắt khi Google SSO đã ổn định.</p>
      </div>

      <button onClick={save} className="rounded-lg bg-brand px-5 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700">Lưu cấu hình</button>
    </div>
  );
}
