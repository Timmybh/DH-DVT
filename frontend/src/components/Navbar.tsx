import { NavLink } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-2 text-sm font-medium ${
    isActive ? "bg-brand/10 text-brand" : "text-slate-600 hover:text-brand"
  }`;

export default function Navbar() {
  const { user, logout } = useAuth();

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6 lg:px-8">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border-2 border-amber-300 bg-rose-800 text-sm font-bold text-amber-200">
            DH
          </div>
          <div>
            <p className="text-sm font-bold leading-none text-slate-900">DH-DVT</p>
            <p className="text-xs text-slate-500">Dashboard điều hành</p>
          </div>
        </div>

        <nav className="flex items-center gap-1">
          <NavLink to="/" end className={linkClass}>
            Dashboard
          </NavLink>
          {user?.role === "ADMIN" && (
            <>
              <NavLink to="/admin/users" className={linkClass}>
                Quản lý người dùng
              </NavLink>
              <NavLink to="/admin/import" className={linkClass}>
                Đồng bộ dữ liệu
              </NavLink>
            </>
          )}
        </nav>

        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-brand/10 text-sm font-bold text-brand">
            {user?.full_name?.[0] ?? "?"}
          </div>
          <div className="text-right">
            <p className="text-sm font-medium leading-none text-slate-900">{user?.full_name}</p>
            <p className="text-xs text-slate-500">{user?.role}</p>
          </div>
          <button
            onClick={logout}
            className="ml-2 rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            Đăng xuất
          </button>
        </div>
      </div>
    </header>
  );
}
