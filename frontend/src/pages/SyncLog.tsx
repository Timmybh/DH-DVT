import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorMessage, SyncRun } from "../api/client";
import { StatusBadge } from "../components/Section";
import { useAuth } from "../context/AuthContext";
import { dateTimeVi, duration, num, SOURCE_LABEL } from "../lib/format";

interface SyncCfg {
  enabled: boolean;
  scheduled_time: string;
}

export default function SyncLog() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [cfg, setCfg] = useState<SyncCfg | null>(null);
  const [busy, setBusy] = useState<"" | "egmf" | "plan">("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const [r, c] = await Promise.all([api.get<SyncRun[]>("/sync/runs"), api.get<SyncCfg>("/sync/config")]);
    setRuns(r.data);
    setCfg(c.data);
  }, []);

  useEffect(() => {
    load().catch((e) => setMessage({ ok: false, text: errorMessage(e) }));
  }, [load]);

  const report = (run: SyncRun) => {
    setMessage({
      ok: run.status !== "FAILED",
      text:
        run.status === "FAILED"
          ? `${run.run_code} thất bại: ${run.error_message}`
          : `${run.run_code} ${run.status}: ${num(run.matched)} khớp, ${num(run.unmatched)} chưa khớp.`,
    });
  };

  async function runEgmf() {
    setBusy("egmf");
    setMessage(null);
    try {
      report((await api.post<SyncRun>("/sync/run", { source: "EGMF_REVENUE" })).data);
    } catch (e) {
      setMessage({ ok: false, text: errorMessage(e) });
    } finally {
      setBusy("");
      load();
    }
  }

  async function importPlan() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setBusy("plan");
    setMessage(null);
    try {
      const form = new FormData();
      form.append("file", file);
      report((await api.post<SyncRun>("/sync/import-plan", form, { headers: { "Content-Type": "multipart/form-data" } })).data);
      if (fileRef.current) fileRef.current.value = "";
    } catch (e) {
      setMessage({ ok: false, text: errorMessage(e) });
    } finally {
      setBusy("");
      load();
    }
  }

  async function saveCfg() {
    if (!cfg) return;
    try {
      await api.put("/sync/config", cfg);
      setMessage({ ok: true, text: "Đã lưu lịch đồng bộ." });
    } catch (e) {
      setMessage({ ok: false, text: errorMessage(e) });
    }
  }

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-bold text-slate-900">Sync Log — nhật ký đồng bộ dữ liệu</h1>

      {can("sync.run") && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-sm font-bold text-slate-800">Đồng bộ eGMF (doanh thu XN)</h2>
            <p className="mt-1 text-xs text-slate-500">Đọc doanh thu ngày/tháng/năm từ SQL Server eGMF vào Postgres. Mỗi lần chạy tạo một Sync Run mới.</p>
            <button onClick={runEgmf} disabled={busy !== ""} className="mt-4 w-full rounded-lg bg-brand py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60">
              {busy === "egmf" ? "Đang đồng bộ..." : "Đồng bộ eGMF ngay"}
            </button>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-sm font-bold text-slate-800">Nhập file kế hoạch SX (Excel)</h2>
            <p className="mt-1 text-xs text-slate-500">File .xlsb/.xlsx có các sheet KẾ HOẠCH, PO MỚI, PO MAY XONG, ĐÃ XUẤT, LAO ĐỘNG. Dùng cho Tiến độ và Nhân sự.</p>
            <input ref={fileRef} type="file" accept=".xlsb,.xlsx,.xlsm" className="mt-3 w-full rounded-lg border border-dashed border-slate-300 p-2 text-xs text-slate-600" />
            <button onClick={importPlan} disabled={busy !== ""} className="mt-3 w-full rounded-lg bg-brand py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60">
              {busy === "plan" ? "Đang nhập (vài giây)..." : "Nhập file"}
            </button>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-sm font-bold text-slate-800">Lịch đồng bộ eGMF hằng ngày</h2>
            {cfg && (
              <div className="mt-3 space-y-3">
                <label className="flex items-center gap-2 text-sm text-slate-600">
                  <input type="checkbox" checked={cfg.enabled} onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })} />
                  Bật đồng bộ tự động
                </label>
                <input type="time" value={cfg.scheduled_time} onChange={(e) => setCfg({ ...cfg, scheduled_time: e.target.value })} className="w-full rounded border border-slate-200 px-3 py-1.5 text-sm" />
                <button onClick={saveCfg} className="w-full rounded-lg border border-brand py-2 text-sm font-semibold text-brand hover:bg-brand/5">
                  Lưu lịch
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {message && (
        <div className={`rounded-xl border p-3 text-sm ${message.ok ? "border-green-200 bg-green-50 text-green-800" : "border-red-200 bg-red-50 text-red-700"}`}>{message.text}</div>
      )}

      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full min-w-[980px] text-left text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-xs uppercase text-slate-400">
              <th className="px-4 py-3">Sync Run</th>
              <th>Thời gian</th>
              <th>Nguồn</th>
              <th>Trạng thái</th>
              <th className="text-right">Tổng</th>
              <th className="text-right">Khớp</th>
              <th className="text-right">Chưa khớp</th>
              <th className="text-right">Mơ hồ</th>
              <th className="text-right">Cập nhật</th>
              <th className="text-right">Thời lượng</th>
              <th className="px-4">Trace ID</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} onClick={() => navigate(`/sync/${r.id}`)} className="cursor-pointer border-b border-slate-50 hover:bg-slate-50">
                <td className="px-4 py-3 font-mono text-xs font-semibold text-brand">{r.run_code}{r.retry_of ? " ↻" : ""}</td>
                <td>{dateTimeVi(r.started_at)}</td>
                <td>{SOURCE_LABEL[r.source] ?? r.source}</td>
                <td><StatusBadge status={r.status} /></td>
                <td className="text-right">{num(r.total_records)}</td>
                <td className="text-right">{num(r.matched)}</td>
                <td className={`text-right ${r.unmatched ? "font-semibold text-amber-600" : ""}`}>{num(r.unmatched)}</td>
                <td className="text-right">{num(r.ambiguous)}</td>
                <td className="text-right">{num(r.updated_rows)}</td>
                <td className="text-right">{duration(r.duration_ms)}</td>
                <td className="px-4 font-mono text-xs text-slate-400">{r.trace_id}</td>
              </tr>
            ))}
            {runs.length === 0 && (
              <tr>
                <td colSpan={11} className="py-8 text-center text-slate-400">Chưa có phiên đồng bộ nào.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
