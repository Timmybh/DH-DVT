import { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import SubTabs, { ADMIN_TABS, PLANNING_TABS } from "./components/SubTabs";
import Navbar from "./components/Navbar";
import { useAuth } from "./context/AuthContext";
import { useTheme } from "./theme/ThemeContext";
import Dashboard from "./pages/Dashboard";
import ChangePassword from "./pages/ChangePassword";
import Login from "./pages/Login";
import Planning from "./pages/Planning";
import Versions from "./pages/Versions";
import ColumnConfig from "./pages/planning/ColumnConfig";
import Actual from "./pages/planning/Actual";
import Resources from "./pages/planning/Resources";
import SalesOrders from "./pages/planning/SalesOrders";
import SyncDetail from "./pages/SyncDetail";
import SyncLog from "./pages/SyncLog";
import Alerts from "./pages/admin/Alerts";
import Lifecycle from "./pages/admin/Lifecycle";
import Monitoring from "./pages/admin/Monitoring";
import Snapshots from "./pages/admin/Snapshots";
import ThemeAdmin from "./pages/admin/Theme";
import Audit from "./pages/admin/Audit";
import DashboardConfig from "./pages/admin/DashboardConfig";
import Calendar from "./pages/admin/Calendar";
import Sso from "./pages/admin/Sso";
import Users from "./pages/admin/Users";

function Protected({ children, perm }: { children: ReactNode; perm?: string }) {
  const { user, ready, can } = useAuth();
  const { mode } = useTheme();
  if (!ready) return <p className="p-8 text-sm text-slate-500">Đang tải...</p>;
  if (!user) return <Navigate to="/login" replace />;
  if (user.must_change_password) return <Navigate to="/change-password" replace />;
  if (perm && !can(perm)) return <Navigate to="/" replace />;
  return (
    <div className={`${mode === "dark" ? "dvt-bg dvt-dark" : "dvt-light"} min-h-screen`}>
      <Navbar />
      <main className="mx-auto max-w-[1500px] px-4 py-4 sm:px-6">{children}</main>
    </div>
  );
}

/** /admin → tab quản trị đầu tiên mà người dùng có quyền. */
function AdminIndex() {
  const { ready, can } = useAuth();
  if (!ready) return null;
  const first = ADMIN_TABS.find((t) => can(t.perm));
  return <Navigate to={first ? first.to : "/"} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/change-password" element={<ChangePassword />} />
      <Route path="/" element={<Protected perm="dashboard.view"><Dashboard /></Protected>} />
      <Route path="/planning" element={<Protected perm="planning.view"><SubTabs tabs={PLANNING_TABS}><Planning /></SubTabs></Protected>} />
      <Route path="/planning/versions" element={<Protected perm="planning.view"><SubTabs tabs={PLANNING_TABS}><Versions /></SubTabs></Protected>} />
      <Route path="/planning/calendar" element={<Protected perm="calendar.view"><SubTabs tabs={PLANNING_TABS}><Calendar /></SubTabs></Protected>} />
      <Route path="/planning/resources" element={<Navigate to="/planning/resources/capacity" replace />} />
      <Route path="/planning/resources/:section" element={<Protected perm="planning.view"><SubTabs tabs={PLANNING_TABS}><Resources /></SubTabs></Protected>} />
      <Route path="/planning/actual" element={<Navigate to="/planning/actual/plan-vs-actual" replace />} />
      <Route path="/planning/actual/:section" element={<Protected perm="mapping.view"><SubTabs tabs={PLANNING_TABS}><Actual /></SubTabs></Protected>} />
      <Route path="/planning/so" element={<Protected perm="planning.view"><SubTabs tabs={PLANNING_TABS}><SalesOrders /></SubTabs></Protected>} />
      <Route path="/planning/columns" element={<Protected perm="planning.view"><SubTabs tabs={PLANNING_TABS}><ColumnConfig /></SubTabs></Protected>} />
      <Route path="/admin" element={<AdminIndex />} />
      <Route path="/admin/dashboard" element={<Navigate to="/admin/dashboard/indicators" replace />} />
      <Route path="/admin/dashboard/:section" element={<Protected perm="dashboard.config_view"><SubTabs tabs={ADMIN_TABS}><DashboardConfig /></SubTabs></Protected>} />
      <Route path="/admin/alerts" element={<Protected perm="monitoring.view"><SubTabs tabs={ADMIN_TABS}><Alerts /></SubTabs></Protected>} />
      <Route path="/admin/sync" element={<Protected perm="monitoring.view"><SubTabs tabs={ADMIN_TABS}><SyncLog /></SubTabs></Protected>} />
      <Route path="/admin/sync/:runId" element={<Protected perm="monitoring.view"><SubTabs tabs={ADMIN_TABS}><SyncDetail /></SubTabs></Protected>} />
      <Route path="/admin/users" element={<Protected perm="admin.user_manage"><SubTabs tabs={ADMIN_TABS}><Users /></SubTabs></Protected>} />
      <Route path="/admin/snapshots" element={<Protected perm="snapshot.view"><SubTabs tabs={ADMIN_TABS}><Snapshots /></SubTabs></Protected>} />
      <Route path="/admin/monitoring" element={<Protected perm="monitoring.view"><SubTabs tabs={ADMIN_TABS}><Monitoring /></SubTabs></Protected>} />
      <Route path="/admin/lifecycle" element={<Protected perm="lifecycle.manage"><SubTabs tabs={ADMIN_TABS}><Lifecycle /></SubTabs></Protected>} />
      <Route path="/admin/theme" element={<Protected perm="theme.manage"><SubTabs tabs={ADMIN_TABS}><ThemeAdmin /></SubTabs></Protected>} />
      <Route path="/admin/audit" element={<Protected perm="audit.view"><SubTabs tabs={ADMIN_TABS}><Audit /></SubTabs></Protected>} />
      <Route path="/admin/sso" element={<Protected perm="admin.sso_manage"><SubTabs tabs={ADMIN_TABS}><Sso /></SubTabs></Protected>} />
      <Route path="/sync" element={<Navigate to="/admin/sync" replace />} />
      <Route path="/admin/calendar" element={<Navigate to="/planning/calendar" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
