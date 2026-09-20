import { useCallback, useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "../../api/client";
import { dateTimeVi, num } from "../../lib/format";

interface Dataset {
  key: string; title: string; group: string; description: string; used_by: string; retention: string; rows: number; latest: string | null; table: string;
  columns: { key: string; label: string }[]; filters: { asof: boolean; factory: boolean; search: boolean; parent: string | null };
}
type Row = Record<string, unknown>;

const PAGE = 100;
const th = "px-3 py-2 text-left text-[11px] font-bold uppercase text-slate-400 whitespace-nowrap";
const inp = "rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm";

const cell = (v: unknown): string => {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "✓" : "";
  if (typeof v === "number") return num(v, Number.isInteger(v) ? 0 : 1);
  if (typeof v === "object") return JSON.stringify(v);
  const s = String(v);
  return /^\d{4}-\d{2}-\d{2}T/.test(s) ? dateTimeVi(s) : /^\d{4}-\d{2}-\d{2}$/.test(s) ? `${s.slice(8)}/${s.slice(5, 7)}/${s.slice(0, 4)}` : s;
};

export default function Snapshots() {
  const [catalog, setCatalog] = useState<Dataset[]>([]);
  const [key, setKey] = useState("labor_snapshots");
  const [data, setData] = useState<{ total: number; rows: Row[] }>({ total: 0, rows: [] });
  const [q, setQ] = useState("");
  const [factory, setFactory] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [parent, setParent] = useState("");
  const [offset, setOffset] = useState(0);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.get<Dataset[]>("/admin/snapshots").then((r) => setCatalog(r.data)).catch((e) => setErr(errorMessage(e)));
  }, []);
  const ds = catalog.find((d) => d.key === key);
  const groups = useMemo(() => [...new Set(catalog.map((d) => d.group))].map((g) => ({ g, items: catalog.filter((d) => d.group === g) })), [catalog]);

  const load = useCallback(async () => {
    const r = await api.get(`/admin/snapshots/${key}`, { params: { limit: PAGE, offset, q: q || undefined, factory: factory || undefined, date_from: from || undefined, date_to: to || undefined, parent_id: parent || undefined } });
    setData(r.data);
  }, [key, offset, q, factory, from, to, parent]);
  useEffect(() => {
    const t = setTimeout(() => load().then(() => setErr("")).catch((e) => setErr(errorMessage(e))), 200);
    return () => clearTimeout(t);
  }, [load]);
  useEffect(() => setOffset(0), [key, q, factory, from, to, parent]);
  const pick = (k: string) => { setKey(k); setQ(""); setFactory(""); setFrom(""); setTo(""); setParent(""); };

  return (
    <div className="space-y-4" data-testid="snapshots">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Snapshot</h1>
        <p className="text-xs text-slate-500">Tất cả bảng ảnh chụp / lịch sử theo lần đồng bộ ở một chỗ (chỉ đọc). Mỗi bộ ghi rõ ai dùng (Dashboard, Recheck, Đối soát) và cách giữ dữ liệu. Ảnh chụp lao động dùng cho Dashboard được lưu riêng, không lẫn với bảng lao động của Recheck.</p>
      </div>
      {err && <p className="rounded-lg border border-red-300/50 px-3 py-2 text-sm text-red-700">{err}</p>}
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <nav className="space-y-3" aria-label="Danh mục snapshot" data-testid="snapshot-catalog">
          {groups.map(({ g, items }) => (
            <div key={g}>
              <p className="mb-1 text-[11px] font-bold uppercase text-slate-400">{g}</p>
              <div className="space-y-1">
                {items.map((d) => (
                  <button key={d.key} onClick={() => pick(d.key)} aria-pressed={key === d.key} data-testid={`snap-${d.key}`} className={`w-full rounded-xl border px-3 py-2 text-left text-xs ${key === d.key ? "border-brand bg-indigo-500/15" : "border-slate-200"}`}>
                    <b className="block text-sm">{d.title}</b>
                    <span className="text-slate-500">{num(d.rows)} dòng{d.latest ? ` · mới nhất ${cell(d.latest)}` : ""}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </nav>

        <section className="min-w-0 space-y-3">
          {ds && (
            <div className="rounded-2xl border border-slate-200 bg-white p-4">
              <h2 className="text-sm font-bold">{ds.title} <span className="font-mono text-xs font-normal text-slate-400">{ds.table}</span></h2>
              <p className="mt-1 text-xs text-slate-500">{ds.description}</p>
              <p className="mt-1 text-[11px] text-slate-400"><b>Dùng cho:</b> {ds.used_by} · <b>Giữ dữ liệu:</b> {ds.retention}</p>
            </div>
          )}
          {ds && (
            <div className="flex flex-wrap items-center gap-2">
              {ds.filters.search && <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm..." className={inp} aria-label="Tìm" />}
              {ds.filters.factory && <select value={factory} onChange={(e) => setFactory(e.target.value)} className={inp} aria-label="Xí nghiệp"><option value="">Mọi XN</option>{["XN1", "XN2", "XN3"].map((f) => <option key={f}>{f}</option>)}</select>}
              {ds.filters.asof && <><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={inp} aria-label="Từ ngày" /><input type="date" value={to} onChange={(e) => setTo(e.target.value)} className={inp} aria-label="Đến ngày" /></>}
              {ds.filters.parent && <input value={parent} onChange={(e) => setParent(e.target.value.replace(/\D/g, ""))} placeholder="ID ảnh chụp" className={`${inp} w-32`} aria-label="ID ảnh chụp" data-testid="snap-parent" />}
              <span className="flex-1" />
              <span className="text-xs text-slate-500">{num(offset + 1)}–{num(Math.min(offset + PAGE, data.total))} / {num(data.total)}</span>
              <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} className="rounded-lg border border-slate-200 px-3 py-1 text-xs disabled:opacity-40">‹</button>
              <button disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)} className="rounded-lg border border-slate-200 px-3 py-1 text-xs disabled:opacity-40">›</button>
            </div>
          )}
          <div className="overflow-x-auto rounded-2xl border border-slate-200">
            <table className="w-full text-sm" data-testid="snapshot-table">
              <thead><tr>{ds?.columns.map((c) => <th key={c.key} className={th}>{c.label}</th>)}{key === "labor_snapshots" && <th className={th} />}</tr></thead>
              <tbody>
                {data.rows.map((r, i) => (
                  <tr key={i} className="border-t border-slate-100 align-top">
                    {ds?.columns.map((c) => <td key={c.key} className="max-w-[320px] truncate px-3 py-1.5 whitespace-nowrap" title={typeof r[c.key] === "object" ? JSON.stringify(r[c.key]) : undefined}>{cell(r[c.key])}</td>)}
                    {key === "labor_snapshots" && <td className="px-3 text-right"><button onClick={() => { pick("labor_snapshot_lines"); setParent(String(r.id)); }} className="text-xs text-brand underline">Xem chuyền</button></td>}
                  </tr>
                ))}
                {data.rows.length === 0 && <tr><td colSpan={(ds?.columns.length ?? 1) + 1} className="px-3 py-6 text-center text-slate-400">Chưa có dữ liệu.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
