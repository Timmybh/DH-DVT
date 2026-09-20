import { NavLink } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ADMIN_TABS } from "./SubTabs";
import { ROLE_LABEL } from "../lib/format";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `px-3 py-2 text-sm font-semibold uppercase tracking-wide whitespace-nowrap border-b-2 ${isActive ? "border-white text-white" : "border-transparent text-slate-300 hover:text-white"}`;

export default function Navbar() {
  const { user, can, logout } = useAuth();
  return (
    <header className="border-b border-white/10 bg-[#0b1226]/80 backdrop-blur">
      <div className="mx-auto flex max-w-[1500px] items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg border-2 border-amber-300 bg-rose-800 text-sm font-bold text-amber-200">DVT</div>
          <div className="hidden sm:block">
            <p className="text-sm font-bold leading-none text-white">BẢNG ĐIỀU HÀNH DVT</p>
            <p className="text-xs text-slate-400">Dashboard điều hành</p>
          </div>
        </div>

        <nav className="flex flex-1 items-center justify-center gap-1 overflow-x-auto">
          <NavLink to="/" end className={linkClass}>Dashboard</NavLink>
          {can("planning.view") && <NavLink to="/planning" className={linkClass}>Kế hoạch</NavLink>}
          {ADMIN_TABS.some((t) => can(t.perm)) && <NavLink to="/admin" className={linkClass}>Quản trị</NavLink>}
        </nav>

        <div className="flex items-center gap-3">
          <div className="hidden text-right sm:block">
            <p className="text-sm font-medium leading-none text-white">{user?.full_name}</p>
            <p className="text-xs text-slate-400">{user ? ROLE_LABEL[user.role] : ""}</p>
          </div>
          <NavLink to="/change-password" className="text-xs text-slate-300 hover:text-white">Đổi mật khẩu</NavLink>
          <button onClick={logout} className="rounded-md border border-white/20 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-white/10">
            Đăng xuất
          </button>
        </div>
      </div>
    </header>
  );
}
