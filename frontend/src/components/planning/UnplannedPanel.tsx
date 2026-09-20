import { useEffect, useMemo, useRef, useState } from "react";
import { api, UnplannedDto } from "../../api/client";
import { num } from "../../lib/format";

export interface UnplannedFilters {
  xn: string; // ALL | XN1 | XN2 | XN3 | UNASSIGNED
  quick: string; // ALL | KNOWN | UNASSIGNED
  customer: string;
  season: string;
  sport: string;
  po: string;
  style: string;
  model: string;
  q: string;
}

const EMPTY: UnplannedFilters = { xn: "ALL", quick: "ALL", customer: "", season: "", sport: "", po: "", style: "", model: "", q: "" };
const STORAGE_KEY = "dvt_unplanned_filters";

// Bộ lọc được giữ nguyên khi kéo-thả và qua toàn bộ Edit Session (Correction §7): state ở cấp panel + localStorage.
function loadFilters(): UnplannedFilters {
  try {
    return { ...EMPTY, ...JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") };
  } catch {
    return EMPTY;
  }
}

interface Props {
  baseVersionId: number | null;
  factories: string[];
  editable: boolean;
  excludeIds: Set<number>;
  reloadKey: number;
  onRows: (rows: UnplannedDto[]) => void;
  onDragStart: (id: number) => void;
  onDragEnd: () => void;
}

export default function UnplannedPanel({ baseVersionId, factories, editable, excludeIds, reloadKey, onRows, onDragStart, onDragEnd }: Props) {
  const [filters, setFilters] = useState<UnplannedFilters>(loadFilters);
  const [facets, setFacets] = useState<{ customers: string[]; seasons: string[]; sports: string[] }>({ customers: [], seasons: [], sports: [] });
  const [data, setData] = useState<{ total: number; rows: UnplannedDto[] }>({ total: 0, rows: [] });
  const [loading, setLoading] = useState(false);
  const onRowsRef = useRef(onRows);
  onRowsRef.current = onRows;

  const set = (patch: Partial<UnplannedFilters>) =>
    setFilters((f) => {
      const next = { ...f, ...patch };
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });

  useEffect(() => {
    api.get("/planning/unplanned/facets").then((r) => setFacets(r.data)).catch(() => undefined);
  }, [reloadKey]);

  useEffect(() => {
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const params: Record<string, string | number> = { limit: 500, xn: filters.xn, quick: filters.quick };
        if (baseVersionId) params.base_version_id = baseVersionId;
        (["customer", "season", "sport", "po", "style", "model", "q"] as const).forEach((k) => filters[k] && (params[k] = filters[k]));
        const r = await api.get<{ total: number; rows: UnplannedDto[] }>("/planning/unplanned", { params });
        setData(r.data);
        onRowsRef.current(r.data.rows);
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [filters, baseVersionId, reloadKey]);

  const visible = useMemo(() => data.rows.filter((r) => !excludeIds.has(r.id)), [data.rows, excludeIds]);
  const placedHere = data.rows.length - visible.length;
  const input = "rounded-md border border-slate-200 bg-white px-2 py-1 text-xs";

  return (
    <section className="rounded-2xl border border-slate-200 bg-white shadow-sm" data-testid="unplanned-panel">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
        <div>
          <h2 className="text-sm font-bold text-slate-900">Chưa lên KH (Unplanned)</h2>
          <p className="text-[11px] text-slate-500">
            {num(visible.length)} PO{placedHere ? ` · ${placedHere} đã kéo vào bản nháp` : ""}
            {loading ? " · đang tải..." : ""} · {editable ? "kéo thả vào chuyền phía trên" : "vào Edit Mode để kéo thả"}
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-0.5 text-xs">
          {[
            ["ALL", "Tất cả"],
            ["KNOWN", "Đã biết XN"],
            ["UNASSIGNED", "Chưa xác định XN"],
          ].map(([v, label]) => (
            <button key={v} onClick={() => set({ quick: v })} className={`rounded-md px-2.5 py-1 font-medium ${filters.quick === v ? "bg-white text-brand shadow-sm" : "text-slate-500"}`}>
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50/60 px-4 py-2">
        <select value={filters.xn} onChange={(e) => set({ xn: e.target.value })} className={input} aria-label="Lọc Xí nghiệp">
          <option value="ALL">XN: Tất cả</option>
          {factories.map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
          <option value="UNASSIGNED">Chưa xác định XN</option>
        </select>
        <select value={filters.customer} onChange={(e) => set({ customer: e.target.value })} className={input} aria-label="Khách hàng">
          <option value="">Khách hàng</option>
          {facets.customers.map((c) => <option key={c}>{c}</option>)}
        </select>
        <select value={filters.season} onChange={(e) => set({ season: e.target.value })} className={input} aria-label="Mùa">
          <option value="">Season</option>
          {facets.seasons.map((c) => <option key={c}>{c}</option>)}
        </select>
        <select value={filters.sport} onChange={(e) => set({ sport: e.target.value })} className={input} aria-label="Sport">
          <option value="">Sport</option>
          {facets.sports.map((c) => <option key={c}>{c}</option>)}
        </select>
        <input value={filters.po} onChange={(e) => set({ po: e.target.value })} placeholder="PO Number" className={`${input} w-28`} />
        <input value={filters.style} onChange={(e) => set({ style: e.target.value })} placeholder="Style/CC" className={`${input} w-24`} />
        <input value={filters.model} onChange={(e) => set({ model: e.target.value })} placeholder="Model Code" className={`${input} w-24`} />
        <input value={filters.q} onChange={(e) => set({ q: e.target.value })} placeholder="Tìm nhanh..." className={`${input} min-w-[140px] flex-1`} />
        <button onClick={() => set(EMPTY)} className="rounded-md px-2 py-1 text-xs text-slate-500 hover:bg-slate-200">Xóa lọc</button>
      </div>

      <div className="max-h-[300px] overflow-auto">
        <table className="w-full min-w-[860px] text-left text-xs">
          <thead className="sticky top-0 bg-white">
            <tr className="border-b border-slate-100 text-slate-400">
              <th className="px-3 py-2">XN</th>
              <th>PO</th>
              <th>Style/CC</th>
              <th>Model</th>
              <th>Khách hàng</th>
              <th>Season</th>
              <th>Sport</th>
              <th className="text-right">SL</th>
              <th>CHD</th>
              <th className="px-3">Mô tả</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr
                key={r.id}
                draggable={editable}
                onDragStart={(e) => {
                  e.dataTransfer.setData("text/plain", String(r.id));
                  e.dataTransfer.effectAllowed = "move";
                  onDragStart(r.id);
                }}
                onDragEnd={onDragEnd}
                className={`border-b border-slate-50 ${editable ? "cursor-grab hover:bg-indigo-50/50" : ""}`}
              >
                <td className="px-3 py-1.5">
                  {r.factory_assignment === "KNOWN" ? (
                    <span className="rounded bg-indigo-100 px-1.5 py-0.5 font-semibold text-indigo-700">{r.factory_code}</span>
                  ) : (
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-500">Chưa xác định XN</span>
                  )}
                  {r.mapping_status === "WARNING" && <span title={r.mapping_note} className="ml-1 text-amber-500">⚠</span>}
                </td>
                <td className="font-medium text-slate-800">{r.po_number}</td>
                <td>{r.style_cc}</td>
                <td>{r.model_code}</td>
                <td>{r.customer}</td>
                <td>{r.season}</td>
                <td>{r.sport}</td>
                <td className="text-right">{num(r.quantity)}</td>
                <td>{r.chd ? new Date(r.chd).toLocaleDateString("vi-VN") : "—"}</td>
                <td className="max-w-[260px] truncate px-3 text-slate-500" title={r.description}>{r.description}</td>
              </tr>
            ))}
            {visible.length === 0 && (
              <tr>
                <td colSpan={10} className="py-6 text-center text-slate-400">Không có PO nào khớp bộ lọc.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
