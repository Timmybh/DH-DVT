import { useEffect, useState } from "react";
import { api, ImportJobConfigOut, ImportJobOut } from "../../api/client";

export default function ImportJob() {
  const [jobs, setJobs] = useState<ImportJobOut[]>([]);
  const [config, setConfig] = useState<ImportJobConfigOut | null>(null);
  const [running, setRunning] = useState(false);

  async function load() {
    const [jobsRes, cfgRes] = await Promise.all([
      api.get<ImportJobOut[]>("/admin/etl/jobs"),
      api.get<ImportJobConfigOut>("/admin/etl/config"),
    ]);
    setJobs(jobsRes.data);
    setConfig(cfgRes.data);
  }

  useEffect(() => {
    load();
  }, []);

  async function runNow() {
    setRunning(true);
    await api.post("/admin/etl/run");
    await load();
    setRunning(false);
  }

  async function saveConfig() {
    if (!config) return;
    await api.put("/admin/etl/config", {
      is_enabled: config.is_enabled,
      scheduled_time: config.scheduled_time,
    });
    await load();
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-slate-900">Đồng bộ dữ liệu (SQL Server → Postgres)</h1>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="text-sm font-semibold text-slate-700">Đồng bộ thủ công</h2>
          <p className="mt-1 text-xs text-slate-500">
            Chạy ngay quy trình đọc dữ liệu kế hoạch/SX/đóng gói/giao hàng/QA/vướng mắc từ SQL Server và tính toán vào Postgres.
          </p>
          <button
            onClick={runNow}
            disabled={running}
            className="mt-4 w-full rounded-lg bg-brand py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60"
          >
            {running ? "Đang đồng bộ..." : "Đồng bộ ngay"}
          </button>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-700">Job tự động hàng ngày</h2>
            <span className={`h-2.5 w-2.5 rounded-full ${config?.is_enabled ? "bg-green-500" : "bg-slate-300"}`} />
          </div>

          {config && (
            <div className="mt-4 space-y-3">
              <label className="flex items-center gap-2 text-sm text-slate-600">
                <input
                  type="checkbox"
                  checked={config.is_enabled}
                  onChange={(e) => setConfig({ ...config, is_enabled: e.target.checked })}
                />
                Kích hoạt job tự động
              </label>
              <div>
                <label className="text-xs font-medium text-slate-500">Thời gian chạy hàng ngày ({config.timezone})</label>
                <input
                  type="time"
                  className="mt-1 w-full rounded border border-slate-200 px-3 py-1.5 text-sm"
                  value={config.scheduled_time}
                  onChange={(e) => setConfig({ ...config, scheduled_time: e.target.value })}
                />
              </div>
              <p className="text-xs text-slate-400">
                Lần chạy gần nhất: {config.last_run_at ? new Date(config.last_run_at).toLocaleString("vi-VN") : "Chưa có"}
              </p>
              <button
                onClick={saveConfig}
                className="w-full rounded-lg border border-brand py-2 text-sm font-semibold text-brand hover:bg-brand/5"
              >
                Lưu cấu hình
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-slate-700">Log đồng bộ gần đây</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-xs uppercase text-slate-400">
                <th className="py-2">Loại</th>
                <th className="py-2">Trạng thái</th>
                <th className="py-2">Bắt đầu</th>
                <th className="py-2">Đã nhập</th>
                <th className="py-2">Bỏ qua</th>
                <th className="py-2">Người chạy</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id} className="border-b border-slate-50">
                  <td className="py-2">{j.job_type}</td>
                  <td className="py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        j.status === "SUCCESS"
                          ? "bg-green-100 text-green-700"
                          : j.status === "FAILED"
                            ? "bg-red-100 text-red-700"
                            : "bg-amber-100 text-amber-700"
                      }`}
                    >
                      {j.status}
                    </span>
                  </td>
                  <td className="py-2">{new Date(j.started_at).toLocaleString("vi-VN")}</td>
                  <td className="py-2">{j.rows_imported}</td>
                  <td className="py-2">{j.rows_skipped}</td>
                  <td className="py-2">{j.triggered_by}</td>
                </tr>
              ))}
              {jobs.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-4 text-center text-slate-400">
                    Chưa có lần đồng bộ nào.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
