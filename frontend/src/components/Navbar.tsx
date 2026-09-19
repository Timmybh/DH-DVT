import { NavLink } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ROLE_LABEL } from "../lib/format";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-2 text-sm font-medium whitespace-nowrap ${isActive ? "bg-brand/10 text-brand" : "text-slate-600 hover:text-brand"}`;

export default function Navbar() {
  const { user, can, logout } = useAuth();
  return (
    <header className="border-b border-slate-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-[1500px] items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border-2 border-amber-300 bg-rose-800 text-sm font-bold text-amber-200">DVT</div>
          <div className="hidden sm:block">
            <p className="text-sm font-bold leading-none text-slate-900">BẢNG ĐIỀU HÀNH DVT</p>
            <p className="text-xs text-slate-500">Dashboard điều hành</p>
          </div>
        </div>

        <nav className="flex flex-1 items-center justify-center gap-1 overflow-x-auto">
          <NavLink to="/" end className={linkClass}>Dashboard</NavLink>
          {can("sync.view") && <NavLink to="/sync" className={linkClass}>Sync Log</NavLink>}
          {can("admin.user_manage") && <NavLink to="/admin/users" className={linkClass}>Người dùng</NavLink>}
          {can("audit.view") && <NavLink to="/admin/audit" className={linkClass}>Audit</NavLink>}
          {can("admin.sso_manage") && <NavLink to="/admin/sso" className={linkClass}>Đăng nhập / SSO</NavLink>}
        </nav>

        <div className="flex items-center gap-3">
          <div className="hidden text-right sm:block">
            <p className="text-sm font-medium leading-none text-slate-900">{user?.full_name}</p>
            <p className="text-xs text-slate-500">{user ? ROLE_LABEL[user.role] : ""}</p>
          </div>
          <button onClick={logout} className="rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">
            Đăng xuất
          </button>
        </div>
      </div>
    </header>
  );
}
