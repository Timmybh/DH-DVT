import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, errorMessage, Overview, SyncBrief } from "../../api/client";
import { StatusBadge } from "../../components/Section";
import { useAuth } from "../../context/AuthContext";
import { dateTimeVi, SOURCE_LABEL } from "../../lib/format";

const STALE_HOURS = 48;

function SyncCard({ title, run }: { title: string; run: SyncBrief | null | undefined }) {
  if (!run) {
    return (
      <div className="rounded-xl border border-amber-300/50 bg-amber-500/10 p-4" data-testid="sync-none">
        <p className="font-semibold text-slate-800">{title}</p>
        <p className="mt-1 text-sm text-amber-700">Chưa có lần đồng bộ nào.</p>
      </div>
    );
  }
  const ageH = (Date.now() - new Date(run.started_at).getTime()) / 3600000;
  const stale = ageH > STALE_HOURS;
  const bad = run.status === "FAILED" || run.status === "PARTIAL" || stale;
  return (
    <div className={`rounded-xl border p-4 ${bad ? "border-amber-300/50 bg-amber-500/10" : "border-slate-200"}`} data-testid={`sync-${run.source}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold text-slate-800">{title}</p>
        <StatusBadge status={run.status} />
      </div>
      <p className="mt-2 text-sm text-slate-600">
        Lần gần nhất: <b>{dateTimeVi(run.started_at)}</b> · {run.run_code}
      </p>
      <p className="text-xs text-slate-500">
        {run.matched.toLocaleString("vi-VN")} khớp · {run.unmatched.toLocaleString("vi-VN")} chưa khớp / cần xem · {run.total_records.toLocaleString("vi-VN")} bản ghi
      </p>
      {stale && <p className="mt-1 text-xs font-semibold text-amber-700">Dữ liệu đã cũ hơn {STALE_HOURS} giờ — nên đồng bộ lại.</p>}
      <Link to={`/admin/sync/${run.id}`} className="mt-2 inline-block text-xs text-brand hover:underline">
        Xem chi tiết phiên đồng bộ ›
      </Link>
    </div>
  );
}

/** Quản trị → Cảnh báo: trạng thái đồng bộ dữ liệu và khuyến nghị bảo mật (không đặt trên Dashboard điều hành). */
export default function Alerts() {
  const { user } = useAuth();
  const [sync, setSync] = useState<Overview["sync"] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get<Overview>("/dashboard/overview", { params: { scope: "TONG" } })
      .then((r) => setSync(r.data.sync))
      .catch((e) => setError(errorMessage(e)));
  }, []);

  const warnings = user?.security_warnings ?? [];
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Cảnh báo hệ thống</h1>
        <p className="text-xs text-slate-500">Trạng thái đồng bộ dữ liệu và khuyến nghị bảo mật — chỉ dành cho người quản trị.</p>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}

      <section className="space-y-3">
        <h2 className="text-xs font-bold uppercase text-slate-400">Đồng bộ dữ liệu</h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <SyncCard title={SOURCE_LABEL.EGMF_REVENUE ?? "eGMF"} run={sync?.revenue} />
          <SyncCard title={SOURCE_LABEL.PLAN_EXCEL ?? "File Excel kế hoạch SX"} run={sync?.plan} />
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-xs font-bold uppercase text-slate-400">Khuyến nghị bảo mật</h2>
        {warnings.length === 0 ? (
          <p className="rounded-xl border border-green-300/50 bg-green-500/10 p-3 text-sm text-green-700">Không có khuyến nghị bảo mật nào.</p>
        ) : (
          <div className="rounded-xl border border-orange-300/50 bg-orange-500/10 p-4" data-testid="security-warnings">
            <ul className="list-inside list-disc space-y-1 text-sm text-slate-700">{warnings.map((w) => <li key={w}>{w}</li>)}</ul>
            <Link to="/admin/sso" className="mt-3 inline-block text-xs text-brand hover:underline">Mở cấu hình Đăng nhập / SSO ›</Link>
          </div>
        )}
      </section>
    </div>
  );
}
