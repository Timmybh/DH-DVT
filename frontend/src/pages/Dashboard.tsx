import { useEffect, useState } from "react";
import { api, FactoryPlanSeries, GaugeOut, IndicatorOut, IssueOut, KpiConfigOut } from "../api/client";
import Gauge from "../components/Gauge";
import PlanChart from "../components/PlanChart";
import Sidebar from "../components/Sidebar";
import { useAuth } from "../context/AuthContext";
import KpiConfigModal from "../components/KpiConfigModal";

export default function Dashboard() {
  const { user } = useAuth();
  const [indicators, setIndicators] = useState<IndicatorOut[]>([]);
  const [series, setSeries] = useState<FactoryPlanSeries[]>([]);
  const [gauges, setGauges] = useState<GaugeOut[]>([]);
  const [issues, setIssues] = useState<IssueOut[]>([]);
  const [selectedIndicator, setSelectedIndicator] = useState<IndicatorOut | null>(null);
  const [kpiConfigs, setKpiConfigs] = useState<KpiConfigOut[]>([]);
  const [showKpiModal, setShowKpiModal] = useState(false);
  const [loading, setLoading] = useState(true);

  async function loadAll() {
    setLoading(true);
    const [ind, plan, gauge] = await Promise.all([
      api.get<IndicatorOut[]>("/dashboard/indicators"),
      api.get<FactoryPlanSeries[]>("/dashboard/plan-chart", { params: { days: 14 } }),
      api.get<GaugeOut[]>("/dashboard/gauges"),
    ]);
    setIndicators(ind.data);
    setSeries(plan.data);
    setGauges(gauge.data);
    setLoading(false);
  }

  useEffect(() => {
    loadAll();
  }, []);

  async function handleSelectIndicator(indicator: IndicatorOut) {
    setSelectedIndicator(indicator);
    const { data } = await api.get<IssueOut[]>("/dashboard/issues");
    setIssues(data);
  }

  async function handleSelectFactory(factoryCode: string) {
    const { data } = await api.get<IssueOut[]>("/dashboard/issues", { params: { factory_code: factoryCode } });
    setIssues(data);
    setSelectedIndicator(null);
  }

  async function openKpiModal() {
    const { data } = await api.get<KpiConfigOut[]>("/dashboard/kpi-config");
    setKpiConfigs(data);
    setShowKpiModal(true);
  }

  if (loading) {
    return <p className="text-sm text-slate-500">Đang tải dữ liệu...</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-slate-900">Dashboard điều hành</h1>
        {user?.role === "ADMIN" && (
          <button
            onClick={openKpiModal}
            className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
          >
            Cấu hình KPI
          </button>
        )}
      </div>

      <div className="flex flex-col gap-6 lg:flex-row">
        <Sidebar indicators={indicators} onSelect={handleSelectIndicator} selectedKey={selectedIndicator?.indicator_key ?? null} />

        <div className="flex-1 space-y-6">
          <PlanChart series={series} onSelectFactory={handleSelectFactory} />

          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <h3 className="mb-3 text-sm font-semibold text-slate-700">10 chỉ số Gauge</h3>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5">
              {gauges.map((g) => (
                <Gauge key={g.gauge_slot} label={g.label} value={g.value} target={g.target} unit={g.unit} />
              ))}
            </div>
          </div>

          {(selectedIndicator || issues.length > 0) && (
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <h3 className="mb-3 text-sm font-semibold text-slate-700">
                Chi tiết {selectedIndicator ? `— ${selectedIndicator.label}` : ""}
              </h3>
              {issues.length === 0 ? (
                <p className="text-sm text-slate-400">Không có dữ liệu chi tiết cho ngày hôm nay.</p>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {issues.map((issue) => (
                    <li key={issue.id} className="py-2">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-slate-800">{issue.title}</span>
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                            issue.severity === "HIGH"
                              ? "bg-red-100 text-red-700"
                              : issue.severity === "MEDIUM"
                                ? "bg-amber-100 text-amber-700"
                                : "bg-slate-100 text-slate-600"
                          }`}
                        >
                          {issue.severity}
                        </span>
                      </div>
                      <p className="text-xs text-slate-500">
                        {issue.factory_name ?? "Tổng công ty"} · {issue.description}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>

      {showKpiModal && (
        <KpiConfigModal
          configs={kpiConfigs}
          onClose={() => setShowKpiModal(false)}
          onSaved={async () => {
            setShowKpiModal(false);
            await loadAll();
          }}
        />
      )}
    </div>
  );
}
