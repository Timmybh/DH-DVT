import { ReactNode, useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export interface TabDef {
  to: string;
  label: string;
  perm: string;
  end?: boolean;
}

export const DASHBOARD_TABS: TabDef[] = [
  { to: "/", label: "Trang 1", perm: "dashboard.view", end: true },
  { to: "/dashboard/trang-2", label: "Trang 2", perm: "dashboard.view" },
];

export const PLANNING_TABS: TabDef[] = [
  { to: "/planning", label: "Bảng kế hoạch", perm: "planning.view", end: true },
  { to: "/planning/versions", label: "Phiên bản", perm: "planning.view" },
  { to: "/planning/calendar", label: "Lịch làm việc", perm: "calendar.view" },
  { to: "/planning/resources", label: "Năng suất & nguồn lực", perm: "planning.view" },
  { to: "/planning/roadmap", label: "Roadmap Simulation", perm: "roadmap.view" },
  { to: "/planning/so", label: "Số SO", perm: "planning.view" },
  { to: "/planning/actual", label: "Thực tế & Đối soát", perm: "mapping.view" },
  { to: "/planning/columns", label: "Cấu hình cột & công thức", perm: "planning.view" },
];

export const ADMIN_TABS: TabDef[] = [
  { to: "/admin/alerts", label: "Cảnh báo", perm: "monitoring.view" },
  { to: "/admin/sync", label: "Sync Log", perm: "monitoring.view" },
  { to: "/admin/dashboard", label: "Cấu hình Dashboard", perm: "dashboard.config_view" },
  { to: "/admin/users", label: "Người dùng", perm: "admin.user_manage" },
  { to: "/admin/snapshots", label: "Snapshot", perm: "snapshot.view" },
  { to: "/admin/monitoring", label: "Giám sát", perm: "monitoring.view" },
  { to: "/admin/lifecycle", label: "Vòng đời năm", perm: "lifecycle.manage" },
  { to: "/admin/theme", label: "Giao diện", perm: "theme.manage" },
  { to: "/admin/audit", label: "Audit", perm: "audit.view" },
  { to: "/admin/sso", label: "Đăng nhập / SSO", perm: "admin.sso_manage" },
];

/** Menu 3 gạch gom các tab con của khu vực đang mở (Kế hoạch / Quản trị) — đặt trên thanh điều hướng chính; chỉ hiện mục người dùng có quyền. */
export function SubTabsMenu() {
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const loc = useLocation();
  const tabs = loc.pathname === "/" || loc.pathname.startsWith("/dashboard") ? DASHBOARD_TABS : loc.pathname.startsWith("/planning") ? PLANNING_TABS : loc.pathname.startsWith("/admin") ? ADMIN_TABS : null;
  const allowed = (tabs ?? []).filter((t) => can(t.perm));
  const current = [...allowed].sort((a, b) => b.to.length - a.to.length).find((t) => (t.end ? loc.pathname === t.to : loc.pathname.startsWith(t.to)));

  useEffect(() => setOpen(false), [loc.pathname]);
  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", off);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", off); document.removeEventListener("keydown", esc); };
  }, [open]);

  if (!tabs || allowed.length === 0) return null;
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open} aria-label="Menu chức năng" data-testid="subtabs-menu" className="flex items-center gap-2 rounded-lg border border-white/20 px-2.5 py-1.5 text-slate-200 hover:bg-white/10">
        <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><path d="M2 4.5h14M2 9h14M2 13.5h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
        <span className="whitespace-nowrap text-sm font-semibold text-white">{current?.label ?? "Chức năng"}</span>
      </button>
      {open && (
        <nav role="menu" className="absolute left-0 top-full z-50 mt-1 min-w-56 rounded-xl border border-slate-200 bg-white p-1 shadow-xl">
          {allowed.map((t) => (
            <NavLink key={t.to} to={t.to} end={t.end} role="menuitem" className={({ isActive }) => `block rounded-lg px-3 py-2 text-sm ${isActive ? "bg-indigo-100 font-semibold text-brand" : "text-slate-700 hover:bg-slate-100"}`}>
              {t.label}
            </NavLink>
          ))}
        </nav>
      )}
    </div>
  );
}

/** Vỏ trang con — menu đã nằm trên Navbar nên chỉ hiển thị nội dung. */
export default function SubTabs({ children }: { tabs?: TabDef[]; children: ReactNode }) {
  return <div>{children}</div>;
}
