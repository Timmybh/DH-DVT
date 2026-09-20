import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, Drill, errorMessage, Overview, Signal } from "../api/client";
import DrillDrawer, { DrillTarget } from "../components/DrillDrawer";
import HrSection from "../components/HrSection";
import ProgressSection from "../components/ProgressSection";
import RevenueSection from "../components/RevenueSection";
import SignalsSidebar from "../components/SignalsSidebar";
import { StatusBadge } from "../components/Section";
import { useAuth } from "../context/AuthContext";
import { dateTimeVi, SOURCE_LABEL } from "../lib/format";

interface Meta {
  today: string;
  factories: { code: string; name: string }[];
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [scope, setScope] = useState("TONG");
  const [month, setMonth] = useState("");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [signals, setSignals] = useState<{ good: Signal[]; warn: Signal[] }>({ good: [], warn: [] });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [drill, setDrill] = useState<DrillTarget | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = { scope, month: month || undefined };
      const [ov, sg] = await Promise.all([api.get<Overview>("/dashboard/overview", { params }), api.get("/dashboard/signals", { params })]);
      setOverview(ov.data);
      setSignals(sg.data);
      if (!month) setMonth(ov.data.month);
    } catch (e) {
      setError(errorMessage(e, "Không tải được dữ liệu dashboard"));
    } finally {
      setLoading(false);
    }
  }, [scope, month]);

  useEffect(() => {
    api.get<Meta>("/dashboard/meta").then((r) => setMeta(r.data)).catch(() => undefined);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const t = setInterval(load, 5 * 60 * 1000);
    return () => clearInterval(t);
  }, [load]);

  const handleSignalDrill = (d: Drill) => {
    if (d.kind === "sync_run") navigate(`/admin/sync/${d.id}`);
    else if (d.kind === "sync_log") navigate("/admin/sync");
    else if (d.kind === "revenue") setDrill({ type: "revenue", month: d.month });
    else if (d.kind === "po") setDrill({ type: "po", risk: d.risk });
  };

  const tabs = [{ code: "TONG", name: "Tổng công ty" }, ...(meta?.factories ?? [])];
  const lastSync = overview?.sync.revenue;
  const lastPlan = overview?.sync.plan;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Dashboard điều hành — {overview?.scope_name ?? "..."}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
            {[lastSync, lastPlan].filter(Boolean).map((s) => (
              <span key={s!.id} className="flex items-center gap-1.5">
                {SOURCE_LABEL[s!.source] ?? s!.source}: <b className="text-slate-700">{dateTimeVi(s!.started_at)}</b> <StatusBadge status={s!.status} />
              </span>
            ))}
            {!lastSync && !lastPlan && <span>Chưa có lần đồng bộ nào</span>}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex rounded-xl border border-slate-200 bg-white p-1 shadow-sm">
            {tabs.map((t) => (
              <button
                key={t.code}
                onClick={() => setScope(t.code)}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${scope === t.code ? "bg-brand text-white shadow" : "text-slate-600 hover:bg-slate-50"}`}
              >
                {t.code === "TONG" ? t.name : t.code}
              </button>
            ))}
          </div>
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm shadow-sm"
            aria-label="Chọn tháng"
          />
          <button onClick={load} className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-600 shadow-sm hover:bg-slate-50">
            {loading ? "Đang tải..." : "Làm mới"}
          </button>
        </div>
      </div>

      {scope === "TONG" && <p className="text-xs text-slate-400">Góc nhìn Tổng công ty được cộng dồn từ các đơn vị (xí nghiệp). Chọn XN1/XN2/XN3 để xem riêng từng đơn vị.</p>}

      {overview?.revenue.has_demo && (
        <div className="rounded-xl border-2 border-dashed border-orange-300 bg-orange-50 p-3 text-sm font-medium text-orange-800">
          DỮ LIỆU DOANH THU MẪU — chưa đồng bộ được từ eGMF. Số liệu doanh thu bên dưới chỉ để minh họa; sẽ tự thay bằng số thật khi đồng bộ thành công.
        </div>
      )}
      {!!user?.security_warnings.length && (
        <div className="rounded-xl border border-orange-200 bg-orange-50 p-3 text-xs text-orange-800">
          <p className="mb-1 font-bold">Khuyến nghị bảo mật (chỉ quản trị thấy)</p>
          <ul className="list-inside list-disc space-y-0.5">{user.security_warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
      )}
      {error && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {overview && (
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start">
          <div className="min-w-0 flex-1 space-y-5">
            <RevenueSection data={overview.revenue} onDrill={(code) => setDrill({ type: "revenue", month: overview.month, scope: code })} />
            <ProgressSection data={overview.progress} onDrill={(risk) => setDrill({ type: "po", risk })} />
            <HrSection data={overview.hr} onDrill={() => setDrill({ type: "hr" })} />
          </div>
          <div className="xl:sticky xl:top-4">
            <SignalsSidebar good={signals.good} warn={signals.warn} onDrill={handleSignalDrill} />
          </div>
        </div>
      )}
      {!overview && loading && <p className="text-sm text-slate-500">Đang tải dữ liệu...</p>}

      <DrillDrawer target={drill} scope={scope} onClose={() => setDrill(null)} />
    </div>
  );
}
