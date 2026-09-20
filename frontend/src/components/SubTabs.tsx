import { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export interface TabDef {
  to: string;
  label: string;
  perm: string;
  end?: boolean;
}

export const PLANNING_TABS: TabDef[] = [
  { to: "/planning", label: "Bảng kế hoạch", perm: "planning.view", end: true },
  { to: "/planning/versions", label: "Phiên bản", perm: "planning.view" },
  { to: "/planning/calendar", label: "Lịch làm việc", perm: "calendar.view" },
  { to: "/planning/columns", label: "Cấu hình cột & công thức", perm: "planning.view" },
];

export const ADMIN_TABS: TabDef[] = [
  { to: "/admin/alerts", label: "Cảnh báo", perm: "sync.view" },
  { to: "/admin/sync", label: "Sync Log", perm: "sync.view" },
  { to: "/admin/dashboard", label: "Cấu hình Dashboard", perm: "dashboard.config_view" },
  { to: "/admin/users", label: "Người dùng", perm: "admin.user_manage" },
  { to: "/admin/audit", label: "Audit", perm: "audit.view" },
  { to: "/admin/sso", label: "Đăng nhập / SSO", perm: "admin.sso_manage" },
];

/** Thanh tab con của một khu vực (Kế hoạch / Quản trị); chỉ hiện tab người dùng có quyền. */
export default function SubTabs({ tabs, children }: { tabs: TabDef[]; children: ReactNode }) {
  const { can } = useAuth();
  return (
    <div>
      <nav className="mb-5 flex gap-1 overflow-x-auto border-b border-slate-200">
        {tabs.filter((t) => can(t.perm)).map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.end}
            className={({ isActive }) =>
              `-mb-px whitespace-nowrap border-b-2 px-4 py-2 text-sm font-medium ${isActive ? "border-brand text-brand" : "border-transparent text-slate-500 hover:text-slate-800"}`
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>
      {children}
    </div>
  );
}
