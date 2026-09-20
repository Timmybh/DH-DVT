import { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import SubTabs, { ADMIN_TABS, PLANNING_TABS } from "./components/SubTabs";
import Navbar from "./components/Navbar";
import { useAuth } from "./context/AuthContext";
import Dashboard from "./pages/Dashboard";
import ChangePassword from "./pages/ChangePassword";
import Login from "./pages/Login";
import Planning from "./pages/Planning";
import Versions from "./pages/Versions";
import ColumnConfig from "./pages/planning/ColumnConfig";
import SyncDetail from "./pages/SyncDetail";
import SyncLog from "./pages/SyncLog";
import Audit from "./pages/admin/Audit";
import Calendar from "./pages/admin/Calendar";
import Sso from "./pages/admin/Sso";
import Users from "./pages/admin/Users";

function Protected({ children, perm }: { children: ReactNode; perm?: string }) {
  const { user, ready, can } = useAuth();
  if (!ready) return <p className="p-8 text-sm text-slate-500">Đang tải...</p>;
  if (!user) return <Navigate to="/login" replace />;
  if (user.must_change_password) return <Navigate to="/change-password" replace />;
  if (perm && !can(perm)) return <Navigate to="/" replace />;
  return (
    <div className="dvt-bg dvt-dark min-h-screen">
      <Navbar />
      <main className="mx-auto max-w-[1500px] px-4 py-6 sm:px-6">{children}</main>
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
      <Route path="/planning/columns" element={<Protected perm="planning.view"><SubTabs tabs={PLANNING_TABS}><ColumnConfig /></SubTabs></Protected>} />
      <Route path="/admin" element={<AdminIndex />} />
      <Route path="/admin/sync" element={<Protected perm="sync.view"><SubTabs tabs={ADMIN_TABS}><SyncLog /></SubTabs></Protected>} />
      <Route path="/admin/sync/:runId" element={<Protected perm="sync.view"><SubTabs tabs={ADMIN_TABS}><SyncDetail /></SubTabs></Protected>} />
      <Route path="/admin/users" element={<Protected perm="admin.user_manage"><SubTabs tabs={ADMIN_TABS}><Users /></SubTabs></Protected>} />
      <Route path="/admin/audit" element={<Protected perm="audit.view"><SubTabs tabs={ADMIN_TABS}><Audit /></SubTabs></Protected>} />
      <Route path="/admin/sso" element={<Protected perm="admin.sso_manage"><SubTabs tabs={ADMIN_TABS}><Sso /></SubTabs></Protected>} />
      <Route path="/sync" element={<Navigate to="/admin/sync" replace />} />
      <Route path="/admin/calendar" element={<Navigate to="/planning/calendar" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
