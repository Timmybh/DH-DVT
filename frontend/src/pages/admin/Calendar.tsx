import { useCallback, useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "../../api/client";
import { useAuth } from "../../context/AuthContext";

interface DayType { code: string; name: string; effect: Effect | "CHOICE"; recurrence: "WEEKLY" | "DATE" | "ANY"; color: string; sort_order: number; is_system: boolean; is_active: boolean }
type Repeat = "NONE" | "WEEKLY" | "MONTHLY" | "YEARLY";
type Effect = "OFF" | "WORKING" | "OVERTIME";
interface Rule {
  id: number; scope_type: string; scope_key: string; rule_type: string; effect: Effect; repeat: Repeat; day_type: string; weekday: number | null; month: number | null; month_day: number | null;
  rule_date: string | null; rule_end_date: string | null; valid_from: string | null; valid_to: string | null; note: string; created_by: string; status: "ACTIVE" | "INACTIVE"; status_changed_by: string; status_reason: string;
}
interface Day { date: string; status: string; scope: string; scope_key: string; day_type: string; day_type_name: string; color: string; inherited: boolean; overrides: boolean; note: string }
type Mode = "DATE" | "RANGE" | "WEEKLY" | "MONTHLY" | "YEARLY";
interface Form { effect: "WORKING" | "OFF"; mode: Mode; date: string; end: string; weekday: number; month: number; mday: number; span: "YEAR" | "ALWAYS"; note: string }

const WD_SHORT = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
const WEEKDAYS = ["Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy", "Chủ nhật"];
const EFFECT_LABEL: Record<string, string> = { OFF: "Nghỉ", WORKING: "Làm việc", OVERTIME: "Làm thêm (tăng ca)", CHOICE: "Chọn khi đăng ký (Làm việc / Nghỉ)" };
const REC_LABEL: Record<string, string> = { WEEKLY: "thường lặp hằng tuần", DATE: "thường theo ngày / khoảng ngày", ANY: "linh hoạt" };
const MODE_LABEL: Record<Mode, string> = { DATE: "Ngày cụ thể", RANGE: "Khoảng ngày", WEEKLY: "Lặp hằng tuần", MONTHLY: "Lặp hằng tháng", YEARLY: "Lặp hằng năm" };
const SCOPE_LABEL: Record<string, string> = { COMPANY: "Công ty", XN: "Xí nghiệp", LINE: "Chuyền", DEFAULT: "Mặc định" };
const MONTHS = ["Tháng 1", "Tháng 2", "Tháng 3", "Tháng 4", "Tháng 5", "Tháng 6", "Tháng 7", "Tháng 8", "Tháng 9", "Tháng 10", "Tháng 11", "Tháng 12"];
const inp = "rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm";
const vi = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
const pad = (v: number) => String(v).padStart(2, "0");
const blank = (year: number): Form => ({ effect: "WORKING", mode: "DATE", date: `${year}-01-01`, end: "", weekday: 6, month: 1, mday: 1, span: "YEAR", note: "" });

/** Đăng ký này có hiệu lực trong năm `year` không? */
function inYear(r: Rule, year: number): boolean {
  if (r.repeat === "NONE") return !!r.rule_date && +r.rule_date.slice(0, 4) <= year && year <= +(r.rule_end_date ?? r.rule_date).slice(0, 4);
  return (!r.valid_from || +r.valid_from.slice(0, 4) <= year) && (!r.valid_to || +r.valid_to.slice(0, 4) >= year);
}
function describe(r: Rule): string {
  return `${EFFECT_LABEL[r.effect] ?? r.effect} · ${describeWhen(r)}`;
}
function describeWhen(r: Rule): string {
  const bounds = !r.valid_from && !r.valid_to ? "mọi năm" : r.valid_from?.slice(5) === "01-01" && r.valid_to?.slice(5) === "12-31" && r.valid_from.slice(0, 4) === r.valid_to.slice(0, 4) ? `trong năm ${r.valid_from.slice(0, 4)}` : `${r.valid_from ? `từ ${vi(r.valid_from)}` : ""} ${r.valid_to ? `đến ${vi(r.valid_to)}` : ""}`.trim();
  if (r.repeat === "WEEKLY") return `Mọi ${WEEKDAYS[r.weekday ?? 0]} · ${bounds}`;
  if (r.repeat === "MONTHLY") return `Ngày ${r.month_day} hằng tháng · ${bounds}`;
  if (r.repeat === "YEARLY") return `Ngày ${r.month_day}/${r.month} hằng năm · ${bounds}`;
  return r.rule_end_date && r.rule_end_date !== r.rule_date ? `${vi(r.rule_date!)} → ${vi(r.rule_end_date)}` : vi(r.rule_date!);
}

export default function Calendar() {
  const { can } = useAuth();
  const manage = can("calendar.manage");
  const [types, setTypes] = useState<DayType[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [factories, setFactories] = useState<string[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [scope, setScope] = useState({ type: "COMPANY", xn: "XN1", line: "" });
  const [year, setYear] = useState(new Date().getFullYear());
  const [days, setDays] = useState<Day[]>([]);
  const [forms, setForms] = useState<Record<string, Form>>({});
  const [sel, setSel] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [newType, setNewType] = useState({ name: "", effect: "OFF", recurrence: "DATE", color: "#94a3b8" });

  const loadTypes = useCallback(async () => setTypes((await api.get<DayType[]>("/planning/calendar/types")).data), []);
  const loadRules = useCallback(async () => setRules((await api.get<Rule[]>("/planning/calendar")).data), []);
  useEffect(() => {
    Promise.all([loadTypes(), loadRules()]).catch((e) => setMsg({ ok: false, text: errorMessage(e) }));
    api.get("/dashboard/meta").then((r) => setFactories(r.data.factories.map((f: { code: string }) => f.code))).catch(() => undefined);
  }, [loadTypes, loadRules]);

  const xn = scope.type === "COMPANY" ? "" : scope.xn;
  const line = scope.type === "LINE" ? scope.line.trim() : "";
  const scopeKey = scope.type === "COMPANY" ? "" : scope.type === "XN" ? scope.xn : `${scope.xn}:${line}`;
  const scopeReady = scope.type !== "LINE" || !!line;
  const scopeName = scope.type === "COMPANY" ? "Công ty" : scope.type === "XN" ? scope.xn : `${scope.xn}:${line || "?"}`;

  useEffect(() => {
    api.get<Day[]>("/planning/calendar/resolve", { params: { date_from: `${year}-01-01`, days: 366, xn: xn || undefined, line: xn && line ? line : undefined } })
      .then((r) => setDays(r.data.filter((d) => d.date.startsWith(String(year))))).catch(() => setDays([]));
  }, [year, xn, line, rules, types]);

  const byCode = useMemo(() => new Map(types.map((t) => [t.code, t])), [types]);
  const dayMap = useMemo(() => new Map(days.map((d) => [d.date, d])), [days]);
  const activeTypes = types.filter((t) => t.is_active);

  const isOwn = (r: Rule) => r.scope_type === scope.type && r.scope_key === scopeKey;
  const chain = ["COMPANY", ...(scope.type !== "COMPANY" ? [`XN:${scope.xn}`] : []), ...(scope.type === "LINE" && line ? [`LINE:${scope.xn}:${line}`] : [])];
  const relevant = rules.filter((r) => chain.includes(r.scope_type === "COMPANY" ? "COMPANY" : `${r.scope_type}:${r.scope_key}`) && inYear(r, year) && (showInactive || r.status === "ACTIVE"));
  const selType = activeTypes.find((t) => t.code === sel) ?? activeTypes[0];
  const orderRules = (a: Rule, b: Rule) => (a.repeat === "NONE" ? 0 : 1) - (b.repeat === "NONE" ? 0 : 1) || (a.rule_date ?? "").localeCompare(b.rule_date ?? "") || a.id - b.id;

  const run = async (fn: () => Promise<string | void>) => {
    try {
      const t = await fn();
      if (t) setMsg({ ok: true, text: t });
      await loadRules();
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    }
  };
  const formOf = (t: DayType): Form => forms[t.code] ?? { ...blank(year), mode: t.recurrence === "WEEKLY" ? "WEEKLY" : "DATE" };
  const selForm = selType ? formOf(selType) : blank(year);
  const selList = selType ? relevant.filter((r) => r.day_type === selType.code).sort(orderRules) : [];
  const setForm = (t: DayType, patch: Partial<Form>) => setForms((f) => ({ ...f, [t.code]: { ...formOf(t), ...patch } }));

  const add = (t: DayType) => {
    if (!scopeReady) return setMsg({ ok: false, text: "Nhập mã chuyền trước." });
    const f = formOf(t);
    const repeat: Repeat = f.mode === "DATE" || f.mode === "RANGE" ? "NONE" : f.mode;
    const bounds = repeat !== "NONE" && f.span === "YEAR" ? { valid_from: `${year}-01-01`, valid_to: `${year}-12-31` } : {};
    void run(async () => {
      await api.post("/planning/calendar", {
        scope_type: scope.type, scope_key: scopeKey, day_type: t.code, repeat, note: f.note, ...(t.effect === "CHOICE" ? { effect: f.effect } : {}),
        ...(repeat === "NONE" ? { rule_date: f.date || null, rule_end_date: f.mode === "RANGE" ? f.end || null : null } : {}),
        ...(repeat === "WEEKLY" ? { weekday: f.weekday } : {}), ...(repeat === "MONTHLY" ? { month_day: f.mday } : {}), ...(repeat === "YEARLY" ? { month: f.month, month_day: f.mday } : {}), ...bounds,
      });
      setForms((all) => ({ ...all, [t.code]: { ...f, note: "" } }));
      return `Đã đăng ký "${t.name}" cho ${scopeName}.`;
    });
  };
  // Lịch KHÔNG xóa: "Ngưng áp dụng" (Inactive không tham gia tính, vẫn giữ lịch sử) / "Áp dụng lại"
  const deactivate = (r: Rule) => {
    if (!window.confirm(`Ngưng áp dụng "${describe(r)}"?${scope.type !== "COMPANY" ? " (Xí nghiệp/chuyền sẽ kế thừa lại lịch cấp trên.)" : ""} Đăng ký vẫn được lưu và có thể áp dụng lại.`)) return;
    void run(async () => { await api.post(`/planning/calendar/${r.id}/deactivate`, { reason: "" }); return "Đã ngưng áp dụng đăng ký."; });
  };
  const reactivate = (r: Rule) => void run(async () => { await api.post(`/planning/calendar/${r.id}/activate`, { reason: "" }); return "Đã áp dụng lại đăng ký."; });
  // ghi đè một đăng ký kế thừa: tạo đăng ký NGƯỢC hiệu lực (nghỉ -> làm việc; làm việc/tăng ca -> nghỉ) cho phạm vi đang chỉnh, cùng ngày / cùng kiểu lặp
  const override = (r: Rule) => {
    const want: "WORKING" | "OFF" = r.effect === "OFF" ? "WORKING" : "OFF";
    const t = activeTypes.find((x) => x.effect === "CHOICE") ?? activeTypes.find((x) => x.effect === want);
    if (!t) return setMsg({ ok: false, text: `Chưa có loại ngày ${want === "WORKING" ? "làm việc (VD Ngoại lệ)" : "nghỉ"} để ghi đè — thêm ở Danh mục loại ngày.` });
    if (!window.confirm(`Ghi đè "${describe(r)}" của ${SCOPE_LABEL[r.scope_type]} bằng "${t.name}" (${EFFECT_LABEL[want]}) cho ${scopeName}?`)) return;
    void run(async () => {
      await api.post("/planning/calendar", {
        scope_type: scope.type, scope_key: scopeKey, day_type: t.code, repeat: r.repeat, ...(t.effect === "CHOICE" ? { effect: want } : {}), note: `Ghi đè: ${byCode.get(r.day_type)?.name ?? r.day_type} của ${SCOPE_LABEL[r.scope_type]}`,
        weekday: r.weekday, month: r.month, month_day: r.month_day, rule_date: r.rule_date, rule_end_date: r.rule_end_date, valid_from: r.valid_from, valid_to: r.valid_to,
      });
      return `Đã ghi đè bằng "${t.name}" cho ${scopeName}.`;
    });
  };

  const saveType = async (code: string, body: Partial<DayType>) => {
    try { await api.put(`/planning/calendar/types/${code}`, body); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
    await loadTypes();
  };
  const addType = async () => {
    try { await api.post("/planning/calendar/types", newType); setNewType({ name: "", effect: "OFF", recurrence: "DATE", color: "#94a3b8" }); await loadTypes(); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };
  const templates = async () => {
    try {
      const r = await api.post<{ created: number }>("/planning/calendar/types/templates");
      setMsg({ ok: true, text: `Đã tạo ${r.data.created} loại ngày mẫu — đổi tên, sửa hoặc xóa tùy ý.` });
      await Promise.all([loadTypes(), loadRules()]);
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };

  const monthCells = (m: number) => ({ lead: (new Date(year, m, 1).getDay() + 6) % 7, n: new Date(year, m + 1, 0).getDate() });

  return (
    <div className="space-y-4" data-testid="calendar-page">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Lịch làm việc / nghỉ</h1>
        <p className="text-xs text-slate-500">
          Lịch do <b>người dùng định nghĩa</b> — hệ thống không nạp sẵn. Chọn <b>năm</b>; trong năm có các <b>loại ngày</b> do công ty đặt tên (VD Nghỉ CN, Nghỉ Tết, Nghỉ lễ, Nghỉ khác, Ngoại lệ, Tăng ca); mỗi loại <b>đăng ký ngày chi tiết</b> (từng ngày, hoặc từ ngày đến ngày) và cả <b>kiểu lặp lại</b> (hằng tuần / hằng tháng / hằng năm, trong năm hoặc mọi năm). Loại "Ngoại lệ" chọn Làm việc hoặc Nghỉ cho từng đăng ký.
          Xí nghiệp / chuyền dùng đúng các loại này, kế thừa lịch công ty và có thể <b>ghi đè</b>. Ưu tiên: phạm vi hẹp hơn thắng; trong một phạm vi: ngày cụ thể &gt; lặp hằng năm &gt; hằng tháng &gt; hằng tuần.
        </p>
      </div>
      {msg && <div className={`rounded-xl border p-3 text-sm ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</div>}

      <section className="flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200 bg-white p-3">
        <button onClick={() => setYear(year - 1)} className="rounded-lg border border-slate-300 px-3 py-1 text-sm" aria-label="Năm trước">◀</button>
        <b className="w-20 text-center text-xl" data-testid="cal-year">{year}</b>
        <button onClick={() => setYear(year + 1)} className="rounded-lg border border-slate-300 px-3 py-1 text-sm" aria-label="Năm sau">▶</button>
        <span className="mx-2 text-slate-300">|</span>
        <span className="text-sm font-bold">Phạm vi:</span>
        <select value={scope.type} onChange={(e) => setScope({ ...scope, type: e.target.value })} className={inp} aria-label="Phạm vi" data-testid="scope-type">
          <option value="COMPANY">Công ty</option><option value="XN">Xí nghiệp</option><option value="LINE">Chuyền</option>
        </select>
        {scope.type !== "COMPANY" && <select value={scope.xn} onChange={(e) => setScope({ ...scope, xn: e.target.value })} className={inp} aria-label="Xí nghiệp" data-testid="scope-xn">{factories.map((f) => <option key={f}>{f}</option>)}</select>}
        {scope.type === "LINE" && <input value={scope.line} onChange={(e) => setScope({ ...scope, line: e.target.value })} placeholder="Mã chuyền" className={`${inp} w-24`} aria-label="Chuyền" />}
        <span className="text-xs text-slate-400">{scope.type === "COMPANY" ? "Áp dụng cho mọi xí nghiệp và chuyền." : "Mặc định kế thừa cấp trên; đăng ký ở đây là GHI ĐÈ."}</span>
      </section>

      {types.length === 0 && (
        <section className="rounded-2xl border border-dashed border-slate-300 p-4 text-sm text-slate-500" data-testid="no-types">
          Chưa có loại ngày nào. Thêm loại ở "Danh mục loại ngày" bên dưới, hoặc
          {manage && <button onClick={templates} className="ml-2 rounded-full border border-slate-300 px-3 py-1 text-xs font-semibold text-brand" data-testid="create-templates">tạo bộ loại ngày mẫu</button>} (Nghỉ hàng tuần, Nghỉ Tết, Nghỉ lễ khác, Nghỉ khác, Ngoại lệ, Tăng ca).
        </section>
      )}

      {/* hai vùng: trái = danh mục loại ngày; phải = chi tiết đã đăng ký của loại đang chọn + đăng ký mới */}
      {selType && (
        <div className="grid gap-4 lg:grid-cols-[300px_1fr]" data-testid="master-detail">
          <nav className="space-y-1.5" aria-label="Danh mục loại ngày" data-testid="type-list">
            {activeTypes.map((t) => {
              const n = relevant.filter((r) => r.day_type === t.code).length;
              const on = t.code === selType.code;
              return (
                <button key={t.code} onClick={() => setSel(t.code)} aria-pressed={on} data-testid={`type-${t.code}`}
                  className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left ${on ? "border-brand bg-indigo-500/15" : "border-slate-200 hover:bg-slate-500/5"}`}
                  style={{ borderLeft: `5px solid ${t.color}` }}>
                  <span className="min-w-0 flex-1">
                    <b className="block truncate text-sm">{t.name}</b>
                    <span className="text-[11px] text-slate-400">{t.effect === "CHOICE" ? "Làm việc hoặc Nghỉ" : EFFECT_LABEL[t.effect]}</span>
                  </span>
                  <span className={`pg-chip ${n ? "bg-indigo-500/20 text-indigo-500" : "bg-slate-500/15 text-slate-400"}`} title={`${n} đăng ký trong ${year}`}>{n}</span>
                </button>
              );
            })}
          </nav>

          <section className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4" style={{ borderTop: `4px solid ${selType.color}` }} data-testid={`detail-${selType.code}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="h-3 w-3 rounded-full" style={{ background: selType.color }} />
              <h2 className="text-base font-bold">{selType.name}</h2>
              <span className="pg-chip bg-slate-500/20 text-slate-500">{selType.effect === "CHOICE" ? "Làm việc hoặc Nghỉ" : EFFECT_LABEL[selType.effect]}</span>
              <label className="ml-auto flex items-center gap-1 text-xs text-slate-500"><input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} data-testid="show-inactive" /> hiện cả đã ngưng</label>
              <span className="text-xs text-slate-400">{selList.length} đăng ký trong {year} · {scopeName}</span>
            </div>

            <ul className="mt-3 space-y-1 text-sm" data-testid="registered-list">
              {selList.map((r) => {
                const mine = isOwn(r);
                return (
                  <li key={r.id} className={`flex flex-wrap items-center gap-2 rounded-lg px-3 py-1.5 ${mine ? "bg-slate-500/5" : "opacity-60"}`} data-testid={`rule-${r.id}`}>
                    <span className={`font-medium ${r.status === "INACTIVE" ? "line-through" : ""}`}>{describe(r)}</span>
                    {r.status === "INACTIVE" && <span className="pg-chip bg-slate-500/20 text-slate-500" title={r.status_reason || `Ngưng bởi ${r.status_changed_by}`}>ngưng áp dụng</span>}
                    {r.repeat !== "NONE" && <span className="pg-chip bg-indigo-500/15 text-indigo-500">lặp</span>}
                    {r.note && <span className="text-xs text-slate-400">{r.note}</span>}
                    <span className="ml-auto flex items-center gap-2 text-xs">
                      {!mine && <span className="text-slate-400">kế thừa · {SCOPE_LABEL[r.scope_type]}</span>}
                      {manage && mine && r.status === "ACTIVE" && <button onClick={() => deactivate(r)} className="text-red-500 hover:underline" data-testid={`deactivate-${r.id}`}>Ngưng áp dụng</button>}
                      {manage && mine && r.status === "INACTIVE" && <button onClick={() => reactivate(r)} className="text-brand hover:underline" data-testid={`activate-${r.id}`}>Áp dụng lại</button>}
                      {manage && !mine && <button onClick={() => override(r)} className="text-brand hover:underline" data-testid={`override-${r.id}`}>Ghi đè</button>}
                    </span>
                  </li>
                );
              })}
              {selList.length === 0 && <li className="rounded-lg border border-dashed border-slate-200 px-3 py-4 text-center text-xs text-slate-400">Chưa đăng ký ngày nào cho "{selType.name}" trong {year}.</li>}
            </ul>

            {manage && (
              <div className="mt-4 border-t border-slate-100 pt-4" data-testid={`form-${selType.code}`}>
                <p className="mb-2 text-xs font-bold uppercase text-slate-400">Đăng ký chi tiết{scope.type !== "COMPANY" ? ` — ghi đè cho ${scopeName}` : ""}</p>
                <div className="flex flex-wrap items-end gap-2">
                  {selType.effect === "CHOICE" && (
                    <select value={selForm.effect} onChange={(e) => setForm(selType, { effect: e.target.value as "WORKING" | "OFF" })} className={inp} aria-label={`Hiệu lực ${selType.name}`} data-testid={`effect-${selType.code}`}>
                      <option value="WORKING">Làm việc</option><option value="OFF">Nghỉ</option>
                    </select>
                  )}
                  <select value={selForm.mode} onChange={(e) => setForm(selType, { mode: e.target.value as Mode })} className={inp} aria-label={`Kiểu đăng ký ${selType.name}`} data-testid="mode">
                    {(Object.keys(MODE_LABEL) as Mode[]).map((m) => <option key={m} value={m}>{MODE_LABEL[m]}</option>)}
                  </select>
                  {(selForm.mode === "DATE" || selForm.mode === "RANGE") && <input type="date" value={selForm.date} onChange={(e) => setForm(selType, { date: e.target.value })} className={inp} aria-label="Từ ngày" />}
                  {selForm.mode === "RANGE" && <input type="date" value={selForm.end} min={selForm.date} onChange={(e) => setForm(selType, { end: e.target.value })} className={inp} aria-label="Đến ngày" />}
                  {selForm.mode === "WEEKLY" && <select value={selForm.weekday} onChange={(e) => setForm(selType, { weekday: Number(e.target.value) })} className={inp} aria-label="Thứ">{WEEKDAYS.map((w, i) => <option key={w} value={i}>{w}</option>)}</select>}
                  {selForm.mode === "YEARLY" && <select value={selForm.month} onChange={(e) => setForm(selType, { month: Number(e.target.value) })} className={inp} aria-label="Tháng">{MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}</select>}
                  {(selForm.mode === "MONTHLY" || selForm.mode === "YEARLY") && <input type="number" min={1} max={31} value={selForm.mday} onChange={(e) => setForm(selType, { mday: Number(e.target.value) })} className={`${inp} w-20`} aria-label="Ngày trong tháng" />}
                  {(selForm.mode === "WEEKLY" || selForm.mode === "MONTHLY" || selForm.mode === "YEARLY") && (
                    <select value={selForm.span} onChange={(e) => setForm(selType, { span: e.target.value as "YEAR" | "ALWAYS" })} className={inp} aria-label="Phạm vi thời gian của quy tắc lặp">
                      <option value="YEAR">Lặp lại trong năm {year}</option><option value="ALWAYS">Lặp lại mọi năm</option>
                    </select>
                  )}
                  <input value={selForm.note} onChange={(e) => setForm(selType, { note: e.target.value })} placeholder="Ghi chú (VD: Quốc khánh)" className={`${inp} min-w-[160px] flex-1`} aria-label="Ghi chú" />
                  <button onClick={() => add(selType)} className="rounded-lg bg-brand px-5 py-1.5 text-sm font-semibold text-white" data-testid={`add-${selType.code}`}>Đăng ký</button>
                </div>
              </div>
            )}
          </section>
        </div>
      )}

      {/* lịch cả năm: xem nhanh kết quả sau kế thừa / ghi đè */}
      <details className="rounded-2xl border border-slate-200 bg-white p-4" open data-testid="year-grid">
        <summary className="cursor-pointer text-sm font-bold">Lịch cả năm {year} — {scopeName} (kết quả sau kế thừa / ghi đè)</summary>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {MONTHS.map((name, m) => {
            const { lead, n } = monthCells(m);
            return (
              <div key={name} className="rounded-xl border border-slate-100 p-2">
                <p className="mb-1 text-center text-xs font-bold text-slate-600">{name}</p>
                <div className="grid grid-cols-7 gap-0.5 text-center text-[10px]">
                  {WD_SHORT.map((d) => <div key={d} className="font-semibold text-slate-400">{d}</div>)}
                  {Array.from({ length: lead }).map((_, i) => <div key={`e${i}`} />)}
                  {Array.from({ length: n }).map((_, i) => {
                    const date = `${year}-${pad(m + 1)}-${pad(i + 1)}`;
                    const d = dayMap.get(date);
                    const special = d && (d.status !== "WORKING" || d.day_type === "EXCEPTION");
                    const tip = d ? `${vi(date)} — ${d.status === "WORKING" && !d.day_type ? "Làm việc" : d.day_type_name || EFFECT_LABEL[d.status]}${d.scope !== "DEFAULT" ? ` · ${SCOPE_LABEL[d.scope]}${d.inherited ? " (kế thừa)" : d.overrides ? " (ghi đè công ty)" : ""}` : ""}${d.note ? ` · ${d.note}` : ""}` : vi(date);
                    return (
                      <div key={date} title={tip} data-date={date} data-status={d?.status} data-type={d?.day_type ?? ""} data-inherited={d?.inherited ? "1" : "0"} className="h-6 rounded text-[11px] leading-6"
                        style={{ background: special && d?.color ? `${d.color}44` : undefined, border: d?.overrides ? `2px solid ${d.color || "#0ea5e9"}` : "1px solid transparent", opacity: d?.inherited && special ? 0.7 : 1, color: special && d?.color ? d.color : undefined, fontWeight: special ? 700 : 400 }}>
                        {i + 1}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
          {activeTypes.map((t) => <span key={t.code}><span className="mr-1 inline-block h-2 w-2 rounded" style={{ background: t.color }} />{t.name}</span>)}
          <span><span className="mr-1 inline-block h-2 w-3 rounded border-2 border-slate-400" />viền đậm = ghi đè lịch cấp trên</span><span>màu mờ = kế thừa</span>
        </div>
      </details>

      {/* danh mục loại ngày */}
      <details className="rounded-2xl border border-slate-200 bg-white p-4" open={types.length === 0} data-testid="day-types">
        <summary className="cursor-pointer text-sm font-bold">Danh mục loại ngày (cấp công ty) — {types.length} loại</summary>
        <p className="mb-3 mt-2 text-[11px] text-slate-400">Công ty đặt tên; xí nghiệp / chuyền dùng lại đúng các tên này. Đổi tên / màu áp dụng toàn hệ thống; loại không xóa — chỉ tắt (đang dùng = bỏ chọn). Cột "kiểu thường dùng" chỉ gợi ý kiểu đăng ký mặc định — loại nào cũng đăng ký được theo ngày lẫn kiểu lặp.</p>
        <div className="space-y-1.5">
          {types.map((t) => (
            <div key={t.code} className={`flex flex-wrap items-center gap-2 text-sm ${t.is_active ? "" : "opacity-50"}`}>
              <input type="color" value={t.color} disabled={!manage} onChange={(e) => saveType(t.code, { color: e.target.value })} className="h-7 w-9 cursor-pointer rounded border border-slate-300 bg-transparent" aria-label={`Màu ${t.name}`} />
              <input defaultValue={t.name} key={t.name} disabled={!manage} onBlur={(e) => e.target.value.trim() !== t.name && saveType(t.code, { name: e.target.value.trim() })} className={`${inp} w-52`} aria-label={`Tên ${t.code}`} data-testid={`type-name-${t.code}`} />
              <span className="pg-chip bg-slate-500/20 text-slate-500">{t.effect === "CHOICE" ? "Làm việc hoặc Nghỉ" : EFFECT_LABEL[t.effect]}</span>
              <span className="text-xs text-slate-400">{REC_LABEL[t.recurrence]}</span>
              {manage && <label className="flex items-center gap-1 text-xs text-slate-500"><input type="checkbox" checked={t.is_active} onChange={(e) => saveType(t.code, { is_active: e.target.checked })} /> đang dùng</label>}
            </div>
          ))}
        </div>
        {manage && (
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
            <input type="color" value={newType.color} onChange={(e) => setNewType({ ...newType, color: e.target.value })} className="h-7 w-9 cursor-pointer rounded border border-slate-300 bg-transparent" aria-label="Màu loại mới" />
            <input value={newType.name} onChange={(e) => setNewType({ ...newType, name: e.target.value })} placeholder="Tên loại ngày mới (VD: Nghỉ bảo trì)" className={`${inp} w-64`} aria-label="Tên loại mới" />
            <select value={newType.effect} onChange={(e) => setNewType({ ...newType, effect: e.target.value })} className={inp} aria-label="Hiệu lực">{Object.entries(EFFECT_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            <select value={newType.recurrence} onChange={(e) => setNewType({ ...newType, recurrence: e.target.value })} className={inp} aria-label="Kiểu thường dùng">{Object.entries(REC_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            <button onClick={addType} disabled={!newType.name.trim()} className="rounded-full bg-brand px-4 py-1.5 text-xs font-semibold text-white disabled:opacity-40">+ Thêm loại</button>
            {types.length > 0 && <button onClick={templates} className="rounded-full border border-slate-300 px-3 py-1 text-xs">Bổ sung loại mẫu còn thiếu</button>}
          </div>
        )}
      </details>
    </div>
  );
}
