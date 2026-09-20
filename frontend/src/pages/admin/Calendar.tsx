import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../../api/client";
import { useAuth } from "../../context/AuthContext";

interface Rule {
  id: number;
  scope_type: string;
  scope_key: string;
  rule_type: string;
  weekday: number | null;
  rule_date: string | null;
  note: string;
  created_by: string;
}

const WEEKDAYS = ["Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy", "Chủ nhật"];
const TYPE_LABEL: Record<string, string> = { WEEKLY_OFF: "Nghỉ hằng tuần", DATE_OFF: "Nghỉ theo ngày", OVERTIME: "Làm thêm (Overtime)" };
const STATUS_CLS: Record<string, string> = { WORKING: "bg-white text-slate-700", OFF: "bg-red-100 text-red-700", OVERTIME: "bg-amber-100 text-amber-700" };

export default function Calendar() {
  const { can } = useAuth();
  const manage = can("calendar.manage");
  const [rules, setRules] = useState<Rule[]>([]);
  const [factories, setFactories] = useState<string[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [form, setForm] = useState({ scope_type: "COMPANY", xn: "", line: "", rule_type: "DATE_OFF", weekday: 6, rule_date: "", note: "" });
  const [preview, setPreview] = useState({ xn: "", line: "", month: new Date().toISOString().slice(0, 7) });
  const [days, setDays] = useState<{ date: string; status: string }[]>([]);

  const load = useCallback(async () => setRules((await api.get<Rule[]>("/planning/calendar")).data), []);
  useEffect(() => {
    load().catch((e) => setMsg({ ok: false, text: errorMessage(e) }));
    api.get("/dashboard/meta").then((r) => setFactories(r.data.factories.map((f: { code: string }) => f.code))).catch(() => undefined);
  }, [load]);

  useEffect(() => {
    api
      .get("/planning/calendar/resolve", { params: { date_from: `${preview.month}-01`, days: 31, xn: preview.xn || undefined, line: preview.xn && preview.line ? preview.line : undefined } })
      .then((r) => setDays((r.data as { date: string; status: string }[]).filter((d) => d.date.startsWith(preview.month))))
      .catch(() => setDays([]));
  }, [preview, rules]);

  async function add() {
    const scope_key = form.scope_type === "COMPANY" ? "" : form.scope_type === "XN" ? form.xn : `${form.xn}:${form.line}`;
    try {
      await api.post("/planning/calendar", {
        scope_type: form.scope_type, scope_key, rule_type: form.rule_type,
        weekday: form.rule_type === "WEEKLY_OFF" ? Number(form.weekday) : null,
        rule_date: form.rule_type === "WEEKLY_OFF" ? null : form.rule_date || null, note: form.note,
      });
      setMsg({ ok: true, text: "Đã thêm quy tắc." });
      load();
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    }
  }
  const remove = async (id: number) => {
    await api.delete(`/planning/calendar/${id}`);
    load();
  };

  const inp = "rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm";
  const firstWeekday = days.length ? (new Date(days[0].date).getDay() + 6) % 7 : 0;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Lịch làm việc</h1>
        <p className="text-xs text-slate-500">Mức ngày. Kế thừa Company → Xí nghiệp → Chuyền; phạm vi hẹp hơn thắng. Trạng thái: WORKING / OFF / OVERTIME. "+1 ngày làm việc" bỏ qua ngày OFF.</p>
      </div>
      {msg && <div className={`rounded-xl border p-3 text-sm ${msg.ok ? "border-green-200 bg-green-50 text-green-800" : "border-red-200 bg-red-50 text-red-700"}`}>{msg.text}</div>}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <div className="space-y-4">
          {manage && (
            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="mb-3 text-sm font-bold text-slate-800">Thêm quy tắc</h2>
              <div className="flex flex-wrap items-end gap-2">
                <select value={form.scope_type} onChange={(e) => setForm({ ...form, scope_type: e.target.value })} className={inp} aria-label="Phạm vi">
                  <option value="COMPANY">Công ty</option><option value="XN">Xí nghiệp</option><option value="LINE">Chuyền</option>
                </select>
                {form.scope_type !== "COMPANY" && (
                  <select value={form.xn} onChange={(e) => setForm({ ...form, xn: e.target.value })} className={inp} aria-label="Xí nghiệp">
                    <option value="">XN</option>{factories.map((f) => <option key={f}>{f}</option>)}
                  </select>
                )}
                {form.scope_type === "LINE" && <input value={form.line} onChange={(e) => setForm({ ...form, line: e.target.value })} placeholder="Mã chuyền" className={`${inp} w-24`} />}
                <select value={form.rule_type} onChange={(e) => setForm({ ...form, rule_type: e.target.value })} className={inp} aria-label="Loại quy tắc">
                  {Object.entries(TYPE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
                {form.rule_type === "WEEKLY_OFF" ? (
                  <select value={form.weekday} onChange={(e) => setForm({ ...form, weekday: Number(e.target.value) })} className={inp} aria-label="Thứ">
                    {WEEKDAYS.map((w, i) => <option key={w} value={i}>{w}</option>)}
                  </select>
                ) : (
                  <input type="date" value={form.rule_date} onChange={(e) => setForm({ ...form, rule_date: e.target.value })} className={inp} aria-label="Ngày" />
                )}
                <input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="Ghi chú (VD: Quốc khánh)" className={`${inp} min-w-[160px] flex-1`} />
                <button onClick={add} className="rounded-lg bg-brand px-4 py-1.5 text-sm font-semibold text-white hover:bg-indigo-700">Thêm</button>
              </div>
            </div>
          )}

          <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-xs uppercase text-slate-400"><th className="px-4 py-3">Phạm vi</th><th>Quy tắc</th><th>Ngày / Thứ</th><th>Ghi chú</th><th /></tr>
              </thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id} className="border-b border-slate-50">
                    <td className="px-4 py-2 text-xs font-semibold">{r.scope_type}{r.scope_key ? ` · ${r.scope_key}` : ""}</td>
                    <td>{TYPE_LABEL[r.rule_type]}</td>
                    <td>{r.rule_type === "WEEKLY_OFF" ? WEEKDAYS[r.weekday ?? 0] : r.rule_date ? new Date(r.rule_date).toLocaleDateString("vi-VN") : "—"}</td>
                    <td className="text-xs text-slate-500">{r.note}</td>
                    <td className="px-3 text-right">{manage && <button onClick={() => remove(r.id)} className="text-xs text-red-500 hover:underline">Xóa</button>}</td>
                  </tr>
                ))}
                {rules.length === 0 && <tr><td colSpan={5} className="py-6 text-center text-slate-400">Chưa có quy tắc nào (mọi ngày là ngày làm việc).</td></tr>}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-bold text-slate-800">Xem lịch đã kế thừa</h2>
            <div className="flex gap-2">
              <select value={preview.xn} onChange={(e) => setPreview({ ...preview, xn: e.target.value, line: "" })} className={inp} aria-label="Xem theo XN">
                <option value="">Công ty</option>{factories.map((f) => <option key={f}>{f}</option>)}
              </select>
              {preview.xn && <input value={preview.line} onChange={(e) => setPreview({ ...preview, line: e.target.value })} placeholder="Chuyền" className={`${inp} w-20`} />}
              <input type="month" value={preview.month} onChange={(e) => setPreview({ ...preview, month: e.target.value })} className={inp} />
            </div>
          </div>
          <div className="grid grid-cols-7 gap-1 text-center text-[11px]">
            {["T2", "T3", "T4", "T5", "T6", "T7", "CN"].map((d) => <div key={d} className="font-semibold text-slate-400">{d}</div>)}
            {Array.from({ length: firstWeekday }).map((_, i) => <div key={`e${i}`} />)}
            {days.map((d) => (
              <div key={d.date} className={`rounded-md border border-slate-100 py-1.5 ${STATUS_CLS[d.status]}`} title={d.status}>
                {Number(d.date.slice(8, 10))}
                {d.status === "OVERTIME" && <span className="block text-[9px] font-bold">OT</span>}
              </div>
            ))}
          </div>
          <p className="mt-3 text-[11px] text-slate-400"><span className="mr-1 inline-block h-2 w-2 rounded bg-red-200" /> OFF <span className="ml-3 mr-1 inline-block h-2 w-2 rounded bg-amber-200" /> Overtime</p>
        </div>
      </div>
    </div>
  );
}
