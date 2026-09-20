import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../../api/client";
import { dateTimeVi, num } from "../../lib/format";

interface Snap {
  generated_at: string;
  status: "OK" | "WARNING" | "ERROR";
  app: { name: string; python: string; uptime_hours: number; timezone: string };
  database: { ping_ms: number; size_bytes: number | null };
  sync: { source: string; last_status: string | null; last_run: string | null; last_at: string | null; last_success_age_hours: number | null; duration_ms: number | null }[];
  sync_failed_24h: number;
  scheduler: { enabled: boolean; running: boolean };
  data: { plan_import_age_days: number | null; last_actual_observation: string | null; issued_version: string | null; latest_revenue_date: string | null; mappings: Record<string, number> };
  security: { failed_logins_24h: number; locked_accounts: number; active_users: number; edit_sessions_active: number };
  storage: { archive_bytes: number; archive_dir: string };
  tables: Record<string, number>;
  alerts: { severity: "ERROR" | "WARNING" | "INFO"; code: string; message: string }[];
}

const mb = (b: number | null) => (b === null ? "—" : `${(b / 1048576).toLocaleString("vi-VN", { maximumFractionDigits: 1 })} MB`);
const SEV: Record<string, string> = { ERROR: "border-red-300/50 bg-red-500/10 text-red-700", WARNING: "border-amber-300/50 bg-amber-500/10 text-amber-700", INFO: "border-sky-300/50 bg-sky-500/10 text-sky-700" };

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4">
      <h3 className="mb-2 text-xs font-bold uppercase text-slate-400">{title}</h3>
      <dl className="space-y-1 text-sm">{children}</dl>
    </section>
  );
}
const Row = ({ k, v }: { k: string; v: React.ReactNode }) => (
  <div className="flex items-baseline justify-between gap-3"><dt className="text-slate-500">{k}</dt><dd className="text-right font-semibold">{v}</dd></div>
);

export default function Monitoring() {
  const [snap, setSnap] = useState<Snap | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => api.get<Snap>("/admin/monitoring").then((r) => { setSnap(r.data); setErr(""); }).catch((e) => setErr(errorMessage(e))), []);
  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  if (err) return <p className="rounded-lg border border-red-300/50 px-3 py-2 text-sm text-red-700">{err}</p>;
  if (!snap) return <p className="text-sm text-slate-500">Đang tải...</p>;
  const badge = snap.status === "OK" ? "bg-green-500/20 text-green-600" : snap.status === "WARNING" ? "bg-amber-500/20 text-amber-600" : "bg-red-500/20 text-red-500";
  return (
    <div className="space-y-4" data-testid="monitoring">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-bold text-slate-900">Giám sát vận hành</h1>
        <span className={`rounded-full px-3 py-1 text-xs font-bold ${badge}`} data-testid="monitoring-status">{snap.status}</span>
        <span className="text-xs text-slate-400">Cập nhật {dateTimeVi(snap.generated_at)} · tự làm mới mỗi phút</span>
        <span className="flex-1" />
        <button onClick={load} className="rounded-full border border-slate-300 px-4 py-1.5 text-xs">Làm mới</button>
      </div>

      <div className="space-y-2" data-testid="monitoring-alerts">
        {snap.alerts.length === 0 && <p className="rounded-xl border border-green-300/50 bg-green-500/10 p-3 text-sm text-green-700">Không có cảnh báo vận hành.</p>}
        {snap.alerts.map((a) => <p key={a.code} className={`rounded-xl border p-3 text-sm ${SEV[a.severity]}`}><b>{a.severity}</b> · {a.message}</p>)}
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <Card title="Ứng dụng & cơ sở dữ liệu">
          <Row k="Thời gian chạy" v={`${snap.app.uptime_hours} giờ`} />
          <Row k="Python" v={snap.app.python} />
          <Row k="Múi giờ" v={snap.app.timezone} />
          <Row k="Phản hồi DB" v={`${snap.database.ping_ms} ms`} />
          <Row k="Dung lượng DB" v={mb(snap.database.size_bytes)} />
        </Card>
        <Card title="Đồng bộ">
          {snap.sync.map((s) => (
            <div key={s.source} className="border-b border-slate-100 pb-1 last:border-0">
              <Row k={s.source} v={s.last_status ?? "chưa chạy"} />
              <p className="text-xs text-slate-400">{s.last_run ?? "—"} · thành công gần nhất {s.last_success_age_hours === null ? "—" : `${s.last_success_age_hours} giờ trước`}</p>
            </div>
          ))}
          <Row k="Thất bại 24 giờ qua" v={snap.sync_failed_24h} />
          <Row k="Lịch nền" v={snap.scheduler.enabled ? (snap.scheduler.running ? "Đang chạy" : "DỪNG") : "Tắt"} />
        </Card>
        <Card title="Độ mới dữ liệu">
          <Row k="Phiên bản đang Issue" v={snap.data.issued_version ?? "—"} />
          <Row k="File kế hoạch nhập" v={snap.data.plan_import_age_days === null ? "—" : `${snap.data.plan_import_age_days} ngày trước`} />
          <Row k="Doanh thu mới nhất" v={snap.data.latest_revenue_date ?? "—"} />
          <Row k="Thực tế mới nhất" v={snap.data.last_actual_observation ? dateTimeVi(snap.data.last_actual_observation) : "—"} />
          <Row k="Mapping cần xem" v={num(snap.data.mappings.REVIEW)} />
        </Card>
        <Card title="Bảo mật đăng nhập">
          <Row k="Người dùng hoạt động" v={snap.security.active_users} />
          <Row k="Đăng nhập sai (24 giờ)" v={snap.security.failed_logins_24h} />
          <Row k="Tài khoản đang khóa tạm" v={snap.security.locked_accounts} />
          <Row k="Phiên soạn thảo kế hoạch" v={snap.security.edit_sessions_active} />
        </Card>
        <Card title="Dung lượng lưu trữ">
          <Row k="Thư mục lưu trữ" v={<span className="break-all text-xs">{snap.storage.archive_dir}</span>} />
          <Row k="Đã dùng" v={mb(snap.storage.archive_bytes)} />
        </Card>
        <Card title="Số bản ghi chính">
          {Object.entries(snap.tables).map(([k, v]) => <Row key={k} k={k} v={num(v)} />)}
        </Card>
      </div>
    </div>
  );
}
