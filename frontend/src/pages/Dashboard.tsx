import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, Drill, errorMessage, RuntimeResponse } from "../api/client";
import DashboardCanvas from "../components/dashboard/DashboardCanvas";
import { DashActions } from "../components/dashboard/renderers";
import DrillDrawer, { DrillTarget } from "../components/DrillDrawer";

interface Meta {
  today: string;
  factories: { code: string; name: string }[];
}

/** Dashboard runtime: mọi thành phần hiển thị (vị trí, kiểu hiển thị, dữ liệu) đến từ metadata + Rule Registry ở backend. */
export default function Dashboard() {
  const navigate = useNavigate();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [scope, setScope] = useState("TONG");
  const [month, setMonth] = useState("");
  const [runtime, setRuntime] = useState<RuntimeResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [drill, setDrill] = useState<DrillTarget | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await api.get<RuntimeResponse>("/dashboard/runtime", { params: { scope, month: month || undefined } });
      setRuntime(r.data);
      if (!month) setMonth(r.data.header.month);
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

  const currentMonth = runtime?.header.month ?? month;
  const actions: DashActions = useMemo(
    () => ({
      month: currentMonth,
      drillRevenue: (code) => setDrill({ type: "revenue", month: currentMonth, scope: code }),
      drillOrder: (kind, status) => setDrill({ type: "order", kind, status, month: currentMonth }),
      drillQa: (category) => setDrill({ type: "qa", category, month: currentMonth }),
      drillPo: (risk) => setDrill({ type: "po", risk }),
      drillHr: () => setDrill({ type: "hr" }),
      drillSignal: (d: Drill) => {
        if (d.kind === "sync_run") navigate(`/admin/sync/${d.id}`);
        else if (d.kind === "sync_log") navigate("/admin/sync");
        else if (d.kind === "revenue") setDrill({ type: "revenue", month: d.month });
        else if (d.kind === "po") setDrill({ type: "po", risk: d.risk });
      },
    }),
    [currentMonth, navigate],
  );

  const tabs = [{ code: "TONG", name: "Tổng công ty" }, ...(meta?.factories ?? [])];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Dashboard điều hành — {runtime?.header.scope_name ?? "..."}</h1>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex rounded-xl border border-slate-200 bg-white p-1 shadow-sm">
            {tabs.map((t) => (
              <button
                key={t.code}
                onClick={() => setScope(t.code)}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium ${scope === t.code ? "bg-brand text-white shadow" : "text-slate-600 hover:bg-slate-50"}`}
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

      {runtime?.header.has_demo && (
        <div className="rounded-xl border-2 border-dashed border-orange-300 bg-orange-50 p-3 text-sm font-medium text-orange-800">
          DỮ LIỆU DOANH THU MẪU — chưa đồng bộ được từ eGMF. Số liệu doanh thu bên dưới chỉ để minh họa; sẽ tự thay bằng số thật khi đồng bộ thành công.
        </div>
      )}
      {error && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {runtime && <DashboardCanvas runtime={runtime} actions={actions} />}
      {!runtime && loading && <p className="text-sm text-slate-500">Đang tải dữ liệu...</p>}

      <DrillDrawer target={drill} scope={scope} onClose={() => setDrill(null)} />
    </div>
  );
}
