import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ComposedChart, LabelList, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useAuth } from "../context/AuthContext";
import { api, errorMessage } from "../api/client";
import LoadingBar from "../components/LoadingBar";
import { dateVi, num, pct } from "../lib/format";

interface Cell { plan: number | null; actual: number | null; pct: number | null; labor_total: number | null; labor_present: number | null; labor_absent: number | null; absent_rate: number | null; dtbq_present: number | null }
interface LineRow { factory: string; line: string; style: string; brand: string; customer: string; price: number | null; qty: number; plan_qty: number | null; pct: number | null; production_days: number | null; revenue_plan: number | null; revenue_actual: number | null; labor_may: number | null; labor_hs: number | null; nsld_may: number | null; ns_present: number | null; efficiency_dcl: number | null; efficiency_other: number | null }
interface Summ { labor_may: number | null; labor_hs: number | null; plan_qty: number | null; qty: number | null; pct: number | null; revenue_plan: number | null; revenue_actual: number | null; nsld_may: number | null; ns_present: number | null; efficiency_dcl: number | null; efficiency_other: number | null; labor_list: number | null; labor_present_erp: number | null; labor_absent: number | null; absent_rate: number | null; labor_indirect: number | null; avg_revenue_per_present: number | null; ns_all_labor?: number | null }
interface Bar1 { label: string; value: number | null; status: "TARGET" | "ACHIEVED" | "MISSED" | null }
interface Charts { targets: Record<string, number>; may_by_day: Bar1[]; hieu_suat: Bar1[]; hien_dien: Bar1[] }
interface Page2 { dtbq_charts: Charts | null; line_summaries: Record<string, Summ> | null; lines: LineRow[]; date: string; has_data: boolean; unit: string; factories: string[]; day: Record<string, Cell> | null; series: { date: string; cells: Record<string, Cell> }[] }

const COLORS: Record<string, string> = { TONG: "#4c9aff", XN1: "#16a34a", XN2: "#f59e0b", XN3: "#a855f7" };
const th = "px-2 py-2 text-right text-xs font-semibold text-slate-400";
const td = "px-2 py-1.5 text-right";
const BAR_COLOR = { TARGET: "#00e5c0", ACHIEVED: "#0a66ff", MISSED: "#e8792f" } as const;

/** Biểu đồ cột "Thực hiện DTBQ": cột Mục tiêu (xanh ngọc), Đạt (xanh dương, ≥ mục tiêu), Không đạt (cam). */
function TargetBars({ title, bars, target, unit, testid, onEdit }: { title: string; bars: Bar1[]; target: number; unit: string; testid: string; onEdit?: (v: number) => void }) {
  const data = bars.map((b) => ({ ...b, name: /^\d{4}-\d{2}-\d{2}$/.test(b.label) ? `${b.label.slice(8)}/${b.label.slice(5, 7)}` : b.label }));
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-3" data-testid={testid}>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-bold text-slate-700">{title}</h2>
        {onEdit && <label className="flex items-center gap-1 text-[11px] text-slate-500">Mục tiêu ({unit})
          <input type="number" min={1} step="0.5" defaultValue={target} key={target} onBlur={(e) => Number(e.target.value) > 0 && Number(e.target.value) !== target && onEdit(Number(e.target.value))} className="w-16 rounded border border-slate-300 px-1 py-0.5 text-right" aria-label={`Mục tiêu ${title}`} />
        </label>}
      </div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 22, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#94a3b833" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} /><YAxis tick={{ fontSize: 11 }} domain={[0, "dataMax + 5"]} />
            <Tooltip formatter={(v: unknown) => (v === null || v === undefined ? "—" : Number(v).toFixed(2))} />
            <Bar dataKey="value" isAnimationActive={false}>
              {data.map((d, i) => <Cell key={i} fill={d.status ? BAR_COLOR[d.status] : "#94a3b8"} />)}
              <LabelList dataKey="value" position="top" formatter={(v: unknown) => (v === null || v === undefined ? "" : Number(v).toFixed(2))} style={{ fontSize: 11, fontWeight: 700 }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 flex justify-center gap-4 text-[11px] text-slate-500">
        {([["TARGET", "Mục tiêu"], ["ACHIEVED", "Đạt"], ["MISSED", "Không đạt"]] as const).map(([k, l]) => <span key={k} className="flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: BAR_COLOR[k] }} />{l}</span>)}
      </div>
    </section>
  );
}
const label = (c: string) => (c === "TONG" ? "Toàn công ty" : c);

/** Trang 2: báo cáo năng suất theo ngày (dựng theo sheet "23"). Ngày chọn quyết định mọi số liệu; ngày không có dữ liệu → "Không có dữ liệu". */
export default function DashboardPage2() {
  const [date, setDate] = useState("");
  const [data, setData] = useState<Page2 | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [scope, setScope] = useState("TONG");
  const { can } = useAuth();
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    api.get<Page2>("/dashboard/page2", { params: { date: date || undefined } })
      .then((r) => { if (!alive) return; setData(r.data); if (!date) setDate(r.data.date); })
      .catch((e) => alive && setError(errorMessage(e, "Không tải được dữ liệu Trang 2")))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [date, reload]);

  const codes = data ? ["TONG", ...data.factories] : [];
  const trend = (data?.series ?? []).map((s) => {
    const row: Record<string, number | string | null> = { date: `${s.date.slice(8)}/${s.date.slice(5, 7)}` };
    codes.forEach((c) => { row[c] = s.cells[c]?.dtbq_present ?? null; });
    row.actual = s.cells[scope]?.actual ?? null;
    row.plan = s.cells[scope]?.plan ?? null;
    return row;
  });

  return (
    <div className="space-y-4" data-testid="dashboard-page2">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold text-slate-900">Báo cáo năng suất ngày {date ? dateVi(date) : ""}</h1>
          <p className="text-xs text-slate-500">Doanh thu và lao động theo xí nghiệp{data ? ` · đơn vị ${data.unit}` : ""}</p>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-600">Ngày
          <input type="date" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900" data-testid="page2-date" />
        </label>
      </div>

      {error && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {loading && <LoadingBar />}

      {!loading && data && !data.has_data && <p className="rounded-xl border border-slate-200 p-6 text-center text-sm text-slate-500" data-testid="page2-nodata">Không có dữ liệu</p>}

      {!loading && data?.has_data && (
        <>
          {data.day && <section className="overflow-x-auto rounded-2xl border border-slate-200 bg-white p-3">
            <table className="w-full min-w-[820px] text-sm">
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="px-2 py-2 text-left text-xs font-semibold text-slate-400">Xí nghiệp</th>
                  <th className={th}>Doanh thu KH</th><th className={th}>Doanh thu TH</th><th className={th}>% hoàn thành</th>
                  <th className={th}>LĐ danh sách</th><th className={th}>LĐ có mặt</th><th className={th}>LĐ vắng</th><th className={th}>Tỉ lệ vắng</th>
                  <th className={th}>DTBQ / LĐ có mặt</th>
                </tr>
              </thead>
              <tbody>
                {codes.map((c) => {
                  const v = data.day![c];
                  return (
                    <tr key={c} className={`border-b border-slate-100 ${c === "TONG" ? "font-bold" : ""}`}>
                      <td className="px-2 py-1.5 text-left">{label(c)}</td>
                      <td className={td}>{num(v.plan)}</td><td className={td}>{num(v.actual)}</td><td className={td}>{pct(v.pct === null ? null : v.pct * 100)}</td>
                      <td className={td}>{num(v.labor_total)}</td><td className={td}>{num(v.labor_present)}</td><td className={td}>{num(v.labor_absent)}</td>
                      <td className={td}>{pct(v.absent_rate === null ? null : v.absent_rate * 100)}</td><td className={td}>{num(v.dtbq_present, 2)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>}

          {data.lines.length > 0 && (
            <section className="overflow-x-auto rounded-2xl border border-slate-200 bg-white p-3" data-testid="page2-lines">
              <h2 className="mb-2 text-sm font-bold text-slate-700">Năng suất theo tổ và mã hàng</h2>
              <table className="w-full min-w-[1400px] text-xs">
                <thead>
                  <tr className="border-b border-slate-200 text-slate-400">
                    <th className="px-2 py-2 text-left">XN</th><th className="px-2 text-left">Tổ</th><th className={th}>SLĐ may</th><th className={th}>SLĐ hiệu suất</th>
                    <th className="px-2 text-left">Mã hàng</th><th className="px-2 text-left">Brand</th><th className={th}>Ngày SX</th><th className={th}>Đơn giá</th>
                    <th className={th}>NS kế hoạch</th><th className={th}>NS thực hiện</th><th className={th}>% HT</th><th className={th}>DT kế hoạch</th><th className={th}>DT thực hiện</th>
                    <th className={th}>NSLĐBQ may</th><th className={th}>NS/LĐ hiện diện</th><th className={th}>HS DCL</th><th className={th}>HS hàng khác</th><th className="px-2 text-left">Khách hàng</th>
                  </tr>
                </thead>
                <tbody>
                  {[...data.factories, "TONG"].map((code) => {
                    const p1 = (v: number | null | undefined) => (v === null || v === undefined ? "—" : pct(v * 100));
                    const rs = code === "TONG" ? [] : data.lines.filter((l) => l.factory === code);
                    const sm = data.line_summaries?.[code];
                    return [
                      ...rs.map((l, i) => {
                        const first = i === 0 || rs[i - 1].line !== l.line;
                        return (
                          <tr key={`${l.factory}-${l.line}-${l.style}`} className={`border-b border-slate-100 ${first ? "border-t border-slate-200" : ""}`}>
                            <td className="px-2 py-1 font-medium">{i === 0 ? l.factory : ""}</td><td className="px-2">{first ? l.line : ""}</td>
                            <td className={td}>{num(l.labor_may, 1)}</td><td className={td}>{num(l.labor_hs, 1)}</td>
                            <td className="px-2">{l.style}</td><td className="px-2">{l.brand || "—"}</td><td className={td}>{l.production_days ?? "—"}</td><td className={td}>{l.price ?? "—"}</td>
                            <td className={td}>{num(l.plan_qty)}</td><td className={td}>{num(l.qty)}</td><td className={td}>{p1(l.pct)}</td>
                            <td className={td}>{num(l.revenue_plan)}</td><td className={td}>{num(l.revenue_actual)}</td>
                            <td className={td}>{l.nsld_may ?? "—"}</td><td className={td}>{l.ns_present ?? "—"}</td>
                            <td className={td}>{p1(l.efficiency_dcl)}</td><td className={td}>{p1(l.efficiency_other)}</td><td className="px-2">{l.customer || "—"}</td>
                          </tr>
                        );
                      }),
                      sm && (rs.length > 0 || code === "TONG") ? (
                        <tr key={`sum-${code}`} className="border-b border-slate-300 bg-slate-500/10 font-bold" data-testid={`sum-${code}`}>
                          <td className="px-2 py-1.5" colSpan={2}>{code === "TONG" ? "Toàn công ty" : `Tổng ${code}`}</td>
                          <td className={td}>{num(sm.labor_may, 1)}</td><td className={td}>{num(sm.labor_hs, 1)}</td><td colSpan={4} />
                          <td className={td}>{num(sm.plan_qty)}</td><td className={td}>{num(sm.qty)}</td><td className={td}>{p1(sm.pct)}</td>
                          <td className={td}>{num(sm.revenue_plan)}</td><td className={td}>{num(sm.revenue_actual)}</td>
                          <td className={td}>{sm.nsld_may ?? "—"}</td><td className={td}>{code === "TONG" ? (sm.ns_all_labor ?? "—") : (sm.ns_present ?? "—")}</td>
                          <td className={td}>{p1(sm.efficiency_dcl)}</td><td className={td}>{p1(sm.efficiency_other)}</td><td />
                        </tr>
                      ) : null,
                    ];
                  })}
                </tbody>
              </table>
              {data.line_summaries && (
                <table className="mt-4 w-full min-w-[640px] text-xs" data-testid="page2-labor-block">
                  <thead><tr className="border-b border-slate-200 text-slate-400"><th className="px-2 py-2 text-left">Lao động</th><th className={th}>LĐ danh sách</th><th className={th}>LĐ hiện diện</th><th className={th}>LĐ vắng</th><th className={th}>Tỉ lệ vắng</th><th className={th}>LĐ gián tiếp</th><th className={th}>DT bình quân / LĐ hiện diện</th></tr></thead>
                  <tbody>
                    {[...data.factories, "TONG"].map((c) => { const m = data.line_summaries![c]; return (
                      <tr key={c} className={`border-b border-slate-100 ${c === "TONG" ? "font-bold" : ""}`}>
                        <td className="px-2 py-1">{c === "TONG" ? "Toàn công ty" : c}</td><td className={td}>{num(m.labor_list)}</td><td className={td}>{num(m.labor_present_erp)}</td><td className={td}>{num(m.labor_absent)}</td>
                        <td className={td}>{m.absent_rate === null ? "—" : pct(m.absent_rate * 100)}</td><td className={td}>{num(m.labor_indirect)}</td><td className={td}>{m.avg_revenue_per_present ?? "—"}</td>
                      </tr>); })}
                  </tbody>
                </table>
              )}
              <p className="mt-2 text-[11px] text-slate-400">Kế hoạch: OMM_KeHoachThang; sản lượng: HiPro; hiệu suất = SAM (Decathlon) hoặc SOT (khách hàng khác) × sản lượng ÷ thời gian làm việc ÷ SLĐ hiệu suất. Chuyền chạy nhiều mã hàng: lao động phân bổ theo tỉ lệ sản lượng.</p>
            </section>
          )}

          {data.dtbq_charts && (
            <div className="grid gap-4 lg:grid-cols-3" data-testid="dtbq-charts">
              {([["may_by_day", "DTBQ LĐ may (các ngày gần nhất)", "DTBQ_LD_MAY"], ["hieu_suat", "DTBQ LĐ hiệu suất", "DTBQ_LD_HIEU_SUAT"], ["hien_dien", "DTBQ LĐ hiện diện", "DTBQ_LD_HIEN_DIEN"]] as const).map(([k, title, code]) => (
                <TargetBars key={k} testid={`chart-${k}`} title={`Biểu đồ thực hiện ${title}`} bars={data.dtbq_charts![k]} target={data.dtbq_charts!.targets[code]} unit="USD/người"
                  onEdit={can("resource.manage") ? async (v) => { try { await api.put("/dashboard/productivity-targets", { [code]: v }); setReload((n) => n + 1); } catch (e) { setError(errorMessage(e)); } } : undefined} />
              ))}
            </div>
          )}

          {trend.length > 0 && <section className="rounded-2xl border border-slate-200 bg-white p-3" data-testid="chart-dtbq">
            <h2 className="mb-2 text-sm font-bold text-slate-700">Doanh thu bình quân / LĐ có mặt hàng ngày trong tháng</h2>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trend} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#94a3b833" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Legend formatter={label} />
                  {codes.map((c) => <Line key={c} type="monotone" dataKey={c} name={c} stroke={COLORS[c] ?? "#64748b"} strokeWidth={c === "TONG" ? 3 : 2} dot={{ r: 2 }} connectNulls />)}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>}

          {trend.length > 0 && <section className="rounded-2xl border border-slate-200 bg-white p-3" data-testid="chart-revenue">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-bold text-slate-700">Doanh thu thực hiện so với kế hoạch hàng ngày trong tháng</h2>
              <div className="flex gap-1 text-xs">
                {codes.map((c) => <button key={c} onClick={() => setScope(c)} className={`rounded-full px-3 py-1 ${scope === c ? "bg-brand text-white" : "border border-slate-300 text-slate-600"}`}>{label(c)}</button>)}
              </div>
            </div>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={trend} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#94a3b833" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} /><Tooltip /><Legend />
                  <Bar dataKey="actual" name="Thực hiện" fill="#4c9aff" /><Line type="monotone" dataKey="plan" name="Kế hoạch" stroke="#f59e0b" strokeWidth={2} dot={false} connectNulls />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </section>}
        </>
      )}
    </div>
  );
}
