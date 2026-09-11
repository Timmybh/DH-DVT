import { useEffect, useState } from "react";
import { api, UserOut } from "../../api/client";

export default function Users() {
  const [users, setUsers] = useState<UserOut[]>([]);
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [newUser, setNewUser] = useState({ full_name: "", username: "", email: "", password: "", role: "USER" });

  async function load() {
    const { data } = await api.get<UserOut[]>("/admin/users");
    setUsers(data);
  }

  useEffect(() => {
    load();
  }, []);

  function updateField(id: number, field: keyof UserOut, value: unknown) {
    setUsers((prev) => prev.map((u) => (u.id === id ? { ...u, [field]: value } : u)));
  }

  async function saveUser(u: UserOut) {
    await api.put(`/admin/users/${u.id}`, {
      full_name: u.full_name,
      email: u.email,
      role: u.role,
      is_active: u.is_active,
    });
    await load();
  }

  async function deleteUser(id: number) {
    await api.delete(`/admin/users/${id}`);
    await load();
  }

  async function resetPassword(id: number) {
    const pwd = prompt("Nhập mật khẩu mới:");
    if (!pwd) return;
    await api.post(`/admin/users/${id}/reset-password`, { new_password: pwd });
  }

  async function createUser() {
    await api.post("/admin/users", newUser);
    setShowCreate(false);
    setNewUser({ full_name: "", username: "", email: "", password: "", role: "USER" });
    await load();
  }

  const filtered = users.filter((u) =>
    `${u.full_name} ${u.username} ${u.email} ${u.role}`.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Quản lý người dùng</h1>
          <p className="text-sm text-slate-500">{users.length} tài khoản · Có thể chỉnh sửa và nhấn Lưu</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
        >
          + Thêm người dùng
        </button>
      </div>

      <input
        className="w-full rounded-lg border border-slate-200 px-4 py-2 text-sm"
        placeholder="Tìm theo họ tên, tài khoản, email hoặc vai trò..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      <div className="space-y-3">
        {filtered.map((u) => (
          <div key={u.id} className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
              <div>
                <label className="text-xs font-medium text-slate-500">Họ tên</label>
                <input
                  className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm"
                  value={u.full_name}
                  onChange={(e) => updateField(u.id, "full_name", e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-slate-500">Tên tài khoản</label>
                <input
                  className="mt-1 w-full rounded border border-slate-200 bg-slate-50 px-2 py-1.5 text-sm text-slate-500"
                  value={u.username}
                  disabled
                />
              </div>
              <div>
                <label className="text-xs font-medium text-slate-500">Email</label>
                <input
                  className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm"
                  value={u.email}
                  onChange={(e) => updateField(u.id, "email", e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-slate-500">Vai trò</label>
                <div className="mt-1 flex items-center gap-2">
                  <select
                    className="w-full rounded border border-slate-200 px-2 py-1.5 text-sm"
                    value={u.role}
                    onChange={(e) => updateField(u.id, "role", e.target.value)}
                  >
                    <option value="USER">USER</option>
                    <option value="ADMIN">ADMIN</option>
                  </select>
                  <label className="flex items-center gap-1 text-xs text-slate-600">
                    <input
                      type="checkbox"
                      checked={u.is_active}
                      onChange={(e) => updateField(u.id, "is_active", e.target.checked)}
                    />
                    Hoạt động
                  </label>
                </div>
              </div>
            </div>

            <div className="mt-3 flex justify-end gap-2">
              <button
                onClick={() => deleteUser(u.id)}
                className="rounded-lg bg-red-50 px-4 py-1.5 text-sm font-medium text-red-600 hover:bg-red-100"
              >
                Xóa
              </button>
              <button
                onClick={() => resetPassword(u.id)}
                className="rounded-lg border border-slate-200 px-4 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50"
              >
                Đặt lại mật khẩu
              </button>
              <button
                onClick={() => saveUser(u)}
                className="rounded-lg bg-brand px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
              >
                Lưu thay đổi
              </button>
            </div>
          </div>
        ))}
      </div>

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <h2 className="mb-4 text-lg font-bold text-slate-900">Thêm người dùng</h2>
            <div className="space-y-3">
              <input
                className="w-full rounded border border-slate-200 px-3 py-2 text-sm"
                placeholder="Họ tên"
                value={newUser.full_name}
                onChange={(e) => setNewUser({ ...newUser, full_name: e.target.value })}
              />
              <input
                className="w-full rounded border border-slate-200 px-3 py-2 text-sm"
                placeholder="Tên tài khoản"
                value={newUser.username}
                onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
              />
              <input
                className="w-full rounded border border-slate-200 px-3 py-2 text-sm"
                placeholder="Email"
                value={newUser.email}
                onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
              />
              <input
                type="password"
                className="w-full rounded border border-slate-200 px-3 py-2 text-sm"
                placeholder="Mật khẩu"
                value={newUser.password}
                onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
              />
              <select
                className="w-full rounded border border-slate-200 px-3 py-2 text-sm"
                value={newUser.role}
                onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}
              >
                <option value="USER">USER</option>
                <option value="ADMIN">ADMIN</option>
              </select>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button onClick={() => setShowCreate(false)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">
                Hủy
              </button>
              <button
                onClick={createUser}
                className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
              >
                Tạo tài khoản
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
