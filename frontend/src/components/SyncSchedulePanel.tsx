import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { dateTimeVi, duration, num } from "../lib/format";

interface Sched {
  code: string; name: string; description: string; enabled: boolean; mode: "DAILY" | "INTERVAL"; daily_time: string; interval_minutes: number;
  window_start: string; window_end: string; last_run_at: string | null; last_status: string; last_rows: number; last_changed: number; last_duration_ms: number;
  last_error: string; editable: boolean;
}

const inp = "rounded border border-slate-200 bg-white px-2 py-1 text-xs";

/** Bảng đăng ký tần suất đồng bộ theo từng nguồn dữ liệu (snapshot). Dòng eGMF đầy đủ chỉ hiển thị; các nguồn nhẹ chỉnh được. */
export default function SyncSchedulePanel() {
  const { can } = useAuth();
  const canRun = can("sync.run");
  const [rows, setRows] = useState<Sched[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => setRows((await api.get<Sched[]>("/sync/schedules")).data), []);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [load]);

  const patch = (code: string, p: Partial<Sched>) => setRows((c) => c.map((r) => (r.code === code ? { ...r, ...p } : r)));
  const save = async (r: Sched) => {
    setBusy(r.code);
    try {
      const { enabled, mode, daily_time, interval_minutes, window_start, window_end } = r;
      await api.put(`/sync/schedules/${r.code}`, { enabled, mode, daily_time, interval_minutes, window_start, window_end });
      await load();
      setMsg({ ok: true, text: `Đã lưu tần suất đồng bộ "${r.code}".` });
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } finally { setBusy(""); }
  };
  const runNow = async (r: Sched) => {
    setBusy(r.code);
    try {
      await api.post(`/sync/schedules/${r.code}/run`);
      await load();
      setMsg({ ok: true, text: `Đã chạy "${r.code}".` });
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } finally { setBusy(""); }
  };

  return (
    <section className="space-y-2 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm" data-testid="sync-schedules">
      <h2 className="text-sm font-bold text-slate-800">Tần suất đồng bộ theo nguồn dữ liệu</h2>
      {msg && <p className={`text-xs ${msg.ok ? "text-green-700" : "text-red-600"}`} role="status">{msg.text}</p>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[900px] text-left text-xs">
          <thead>
            <tr className="border-b border-slate-100 text-slate-400"><th className="py-2">Nguồn</th><th>Bật</th><th>Chế độ</th><th>Tần suất</th><th>Lần chạy gần nhất</th><th>Kết quả</th><th /></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.code} className="border-b border-slate-50 align-top" data-testid={`sched-${r.code}`}>
                <td className="max-w-[300px] py-2 pr-3"><p className="font-semibold text-slate-700">{r.name}</p><p className="text-[11px] text-slate-400">{r.description}</p></td>
                <td><input type="checkbox" checked={r.enabled} disabled={!r.editable || !canRun} onChange={(e) => patch(r.code, { enabled: e.target.checked })} aria-label={`Bật ${r.code}`} /></td>
                <td>
                  {r.editable && canRun ? (
                    <select className={inp} value={r.mode} onChange={(e) => patch(r.code, { mode: e.target.value as Sched["mode"] })}><option value="INTERVAL">Mỗi N phút</option><option value="DAILY">Mỗi ngày 1 lần</option></select>
                  ) : (r.mode === "DAILY" ? "Mỗi ngày 1 lần" : "Mỗi N phút")}
                </td>
                <td>
                  {r.mode === "DAILY" ? (
                    r.editable && canRun ? <input type="time" className={inp} value={r.daily_time} onChange={(e) => patch(r.code, { daily_time: e.target.value })} /> : r.daily_time
                  ) : r.editable && canRun ? (
                    <div className="flex flex-wrap items-center gap-1">
                      <input type="number" min={5} max={1440} className={`${inp} w-16`} value={r.interval_minutes} onChange={(e) => patch(r.code, { interval_minutes: Number(e.target.value) })} aria-label="Chu kỳ phút" /> phút, trong
                      <input type="time" className={inp} value={r.window_start} onChange={(e) => patch(r.code, { window_start: e.target.value })} />–
                      <input type="time" className={inp} value={r.window_end} onChange={(e) => patch(r.code, { window_end: e.target.value })} />
                    </div>
                  ) : `${r.interval_minutes} phút (${r.window_start}–${r.window_end})`}
                </td>
                <td>{r.last_run_at ? dateTimeVi(r.last_run_at) : "Chưa chạy"}{r.last_duration_ms ? <span className="text-slate-400"> · {duration(r.last_duration_ms)}</span> : null}</td>
                <td>
                  {r.last_status ? <span className={r.last_status === "FAILED" ? "font-semibold text-red-600" : "text-slate-600"}>{r.last_status}</span> : "—"}
                  {r.last_status && r.editable ? <span className="text-slate-400"> · đọc {num(r.last_rows)}, đổi {num(r.last_changed)}</span> : null}
                  {r.last_error && <p className="max-w-[260px] text-[11px] text-red-600">{r.last_error}</p>}
                </td>
                <td className="whitespace-nowrap py-1">
                  {r.editable && canRun && (
                    <>
                      <button onClick={() => save(r)} disabled={busy === r.code} className="mr-1 rounded-full border border-brand px-3 py-1 text-brand disabled:opacity-50">Lưu</button>
                      <button onClick={() => runNow(r)} disabled={busy === r.code} className="rounded-full border border-slate-300 px-3 py-1 disabled:opacity-50">Chạy ngay</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-slate-400">Mỗi lần chạy nguồn nhẹ chỉ quét lại ngày hôm nay và ghi các dòng mới hoặc thay đổi (cột "đổi"); lượt eGMF đầy đủ đối soát lại từ đầu tháng.</p>
    </section>
  );
}
