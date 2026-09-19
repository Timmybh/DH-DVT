import { useCallback, useEffect, useState } from "react";
import { api, errorMessage, UserRow } from "../../api/client";
import { dateTimeVi, ROLE_LABEL } from "../../lib/format";

const ROLES = ["ADMIN", "PLANNER", "VIEWER"];
const EMPTY = { full_name: "", username: "", email: "", password: "", role: "VIEWER", allow_local_login: true };

export default function Users() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => setUsers((await api.get<UserRow[]>("/admin/users")).data), []);
  useEffect(() => {
    load().catch((e) => setMsg({ ok: false, text: errorMessage(e) }));
  }, [load]);

  const patch = (id: number, field: keyof UserRow, value: unknown) => setUsers((prev) => prev.map((u) => (u.id === id ? { ...u, [field]: value } : u)));
  const wrap = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      setMsg({ ok: true, text: ok });
      await load();
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    }
  };

  const save = (u: UserRow) =>
    wrap(() => api.put(`/admin/users/${u.id}`, { full_name: u.full_name, email: u.email, role: u.role, is_active: u.is_active, allow_local_login: u.allow_local_login }), `Đã lưu ${u.username}`);
  const remove = (u: UserRow) => window.confirm(`Xóa tài khoản ${u.username}?`) && wrap(() => api.delete(`/admin/users/${u.id}`), `Đã xóa ${u.username}`);
  const reset = (u: UserRow) => {
    const pwd = window.prompt(`Mật khẩu mới cho ${u.username} (≥ 8 ký tự, có chữ và số):`);
    if (pwd) wrap(() => api.post(`/admin/users/${u.id}/reset-password`, { new_password: pwd }), `Đã đặt lại mật khẩu ${u.username}`);
  };
  const create = () =>
    wrap(async () => {
      await api.post("/admin/users", form);
      setShowCreate(false);
      setForm(EMPTY);
    }, "Đã tạo tài khoản");

  const filtered = users.filter((u) => `${u.full_name} ${u.username} ${u.email} ${u.role}`.toLowerCase().includes(search.toLowerCase()));
  const input = "mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Quản lý người dùng</h1>
          <p className="text-sm text-slate-500">{users.length} tài khoản · Quản trị / Lập kế hoạch / Xem</p>
        </div>
        <button onClick={() => setShowCreate(true)} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700">+ Thêm người dùng</button>
      </div>

      {msg && <div className={`rounded-xl border p-3 text-sm ${msg.ok ? "border-green-200 bg-green-50 text-green-800" : "border-red-200 bg-red-50 text-red-700"}`}>{msg.text}</div>}
      <input className="w-full rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm" placeholder="Tìm theo họ tên, tài khoản, email, vai trò..." value={search} onChange={(e) => setSearch(e.target.value)} />

      <div className="space-y-3">
        {filtered.map((u) => (
          <div key={u.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
              <label className="text-xs font-medium text-slate-500">Họ tên<input className={input} value={u.full_name} onChange={(e) => patch(u.id, "full_name", e.target.value)} /></label>
              <label className="text-xs font-medium text-slate-500">Tài khoản<input className={`${input} bg-slate-50 text-slate-500`} value={u.username} disabled /></label>
              <label className="text-xs font-medium text-slate-500">Email (dùng cho Google SSO)<input className={input} value={u.email} onChange={(e) => patch(u.id, "email", e.target.value)} /></label>
              <label className="text-xs font-medium text-slate-500">Vai trò
                <select className={input} value={u.role} onChange={(e) => patch(u.id, "role", e.target.value)}>
                  {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]} ({r})</option>)}
                </select>
              </label>
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-4 text-xs text-slate-600">
                <label className="flex items-center gap-1"><input type="checkbox" checked={u.is_active} onChange={(e) => patch(u.id, "is_active", e.target.checked)} /> Hoạt động</label>
                <label className="flex items-center gap-1"><input type="checkbox" checked={u.allow_local_login} onChange={(e) => patch(u.id, "allow_local_login", e.target.checked)} /> Cho phép đăng nhập nội bộ (dự phòng)</label>
                <span className="text-slate-400">Đăng nhập gần nhất: {dateTimeVi(u.last_login_at)}</span>
              </div>
              <div className="flex gap-2">
                <button onClick={() => remove(u)} className="rounded-lg bg-red-50 px-4 py-1.5 text-sm font-medium text-red-600 hover:bg-red-100">Xóa</button>
                <button onClick={() => reset(u)} className="rounded-lg border border-slate-200 px-4 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50">Đặt lại mật khẩu</button>
                <button onClick={() => save(u)} className="rounded-lg bg-brand px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700">Lưu thay đổi</button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <h2 className="mb-4 text-lg font-bold text-slate-900">Thêm người dùng</h2>
            <div className="space-y-3">
              <input className="w-full rounded border border-slate-200 px-3 py-2 text-sm" placeholder="Họ tên" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
              <input className="w-full rounded border border-slate-200 px-3 py-2 text-sm" placeholder="Tên tài khoản" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
              <input className="w-full rounded border border-slate-200 px-3 py-2 text-sm" placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              <input type="password" className="w-full rounded border border-slate-200 px-3 py-2 text-sm" placeholder="Mật khẩu (≥ 8 ký tự, có chữ và số)" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
              <select className="w-full rounded border border-slate-200 px-3 py-2 text-sm" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]} ({r})</option>)}
              </select>
              <label className="flex items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={form.allow_local_login} onChange={(e) => setForm({ ...form, allow_local_login: e.target.checked })} /> Cho phép đăng nhập nội bộ (dự phòng)</label>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button onClick={() => setShowCreate(false)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
              <button onClick={create} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700">Tạo tài khoản</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
