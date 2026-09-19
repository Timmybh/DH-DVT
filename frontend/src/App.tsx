import { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Navbar from "./components/Navbar";
import { useAuth } from "./context/AuthContext";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import SyncDetail from "./pages/SyncDetail";
import SyncLog from "./pages/SyncLog";
import Audit from "./pages/admin/Audit";
import Sso from "./pages/admin/Sso";
import Users from "./pages/admin/Users";

function Protected({ children, perm }: { children: ReactNode; perm?: string }) {
  const { user, ready, can } = useAuth();
  if (!ready) return <p className="p-8 text-sm text-slate-500">Đang tải...</p>;
  if (!user) return <Navigate to="/login" replace />;
  if (perm && !can(perm)) return <Navigate to="/" replace />;
  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-slate-50 to-slate-100 bg-fixed">
      <Navbar />
      <main className="mx-auto max-w-[1500px] px-4 py-6 sm:px-6">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Protected perm="dashboard.view"><Dashboard /></Protected>} />
      <Route path="/sync" element={<Protected perm="sync.view"><SyncLog /></Protected>} />
      <Route path="/sync/:runId" element={<Protected perm="sync.view"><SyncDetail /></Protected>} />
      <Route path="/admin/users" element={<Protected perm="admin.user_manage"><Users /></Protected>} />
      <Route path="/admin/audit" element={<Protected perm="audit.view"><Audit /></Protected>} />
      <Route path="/admin/sso" element={<Protected perm="admin.sso_manage"><Sso /></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
