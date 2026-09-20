import { FormEvent, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { errorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";

export default function ChangePassword() {
  const { user, ready, changePassword, logout } = useAuth();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (!ready) return null;
  if (!user) return <Navigate to="/login" replace />;
  const forced = user.must_change_password;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (next !== confirm) return setError("Mật khẩu nhập lại không khớp");
    setLoading(true);
    try {
      await changePassword(current, next);
      navigate("/", { replace: true });
    } catch (err) {
      setError(errorMessage(err, "Không đổi được mật khẩu"));
    } finally {
      setLoading(false);
    }
  }

  const input = "w-full rounded-lg border-0 bg-slate-100 px-4 py-2.5 text-slate-900 focus:outline-none focus:ring-2 focus:ring-brand";
  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-dark via-indigo-900 to-slate-900 px-4">
      <form onSubmit={submit} className="w-full max-w-md space-y-4 rounded-2xl bg-white p-10 shadow-2xl">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Đổi mật khẩu</h1>
          <p className="mt-1 text-sm text-slate-500">
            {forced ? "Bạn đang dùng mật khẩu tạm/mặc định — phải đặt mật khẩu mới trước khi tiếp tục." : `Tài khoản: ${user.username}`}
          </p>
        </div>
        <label className="block text-sm font-medium text-slate-600">
          Mật khẩu hiện tại
          <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} className={`mt-1 ${input}`} autoComplete="current-password" required />
        </label>
        <label className="block text-sm font-medium text-slate-600">
          Mật khẩu mới <span className="font-normal text-slate-400">(≥ 8 ký tự, có chữ và số)</span>
          <input type="password" value={next} onChange={(e) => setNext(e.target.value)} className={`mt-1 ${input}`} autoComplete="new-password" required />
        </label>
        <label className="block text-sm font-medium text-slate-600">
          Nhập lại mật khẩu mới
          <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} className={`mt-1 ${input}`} autoComplete="new-password" required />
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button type="submit" disabled={loading} className="w-full rounded-lg bg-brand py-2.5 font-semibold text-white hover:bg-indigo-700 disabled:opacity-60">
          {loading ? "Đang lưu..." : "Đổi mật khẩu"}
        </button>
        <div className="flex justify-between text-xs text-slate-400">
          {!forced ? <button type="button" onClick={() => navigate(-1)} className="hover:text-slate-600">← Quay lại</button> : <span />}
          <button type="button" onClick={logout} className="hover:text-slate-600">Đăng xuất</button>
        </div>
      </form>
    </div>
  );
}
