import { CSSProperties, MutableRefObject, useEffect, useMemo, useRef, useState } from "react";
import { api, UnplannedDto } from "../../api/client";
import { num } from "../../lib/format";
import { cellText, Col, sortValue, UNPLANNED_COLS } from "../../lib/planColumns";
import { DragInfo } from "./PlannedGrid";
import { useColumnWidths } from "../../lib/useColumnWidths";
import { useColumnChooser } from "../../lib/useColumnChooser";

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
const CTRL_W = 44;

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
  excludeReturned: Set<string>; // dòng đã trả về nhưng được kéo lại vào kế hoạch trong bản nháp
  extraRows: UnplannedDto[]; // dòng vừa trả về Unplanned trong bản nháp (chưa Commit)
  reloadKey: number;
  drag: MutableRefObject<DragInfo>;
  onRows: (rows: UnplannedDto[]) => void;
  onDropPlanned: (uid: string) => void; // thả dòng Planned xuống đây = trả về Unplanned
  fill?: boolean;
  light?: boolean;
}

export default function UnplannedPanel({ baseVersionId, factories, editable, excludeIds, excludeReturned, extraRows, reloadKey, drag, onRows, onDropPlanned, fill, light }: Props) {
  const [filters, setFilters] = useState<UnplannedFilters>(loadFilters);
  const [facets, setFacets] = useState<{ customers: string[]; seasons: string[]; sports: string[] }>({ customers: [], seasons: [], sports: [] });
  const [data, setData] = useState<{ total: number; rows: UnplannedDto[] }>({ total: 0, rows: [] });
  const [loading, setLoading] = useState(false);
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [dropOver, setDropOver] = useState(false);
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

  const chooser = useColumnChooser("dvt_colvis_unplanned", UNPLANNED_COLS);
  const cols = chooser.cols;
  const cw = useColumnWidths("dvt_cols_unplanned", cols.map((c) => ({ key: c.key, w: c.w })));
  const offsets = useMemo(() => {
    let left = CTRL_W;
    const m = new Map<string, number>();
    cols.forEach((c) => {
      if (c.frozen) {
        m.set(c.key, left);
        left += cw.widthOf(c.key);
      }
    });
    return m;
  }, [cols, cw]);
  const frozenStyle = (c: Col<UnplannedDto>): CSSProperties | undefined => (c.frozen ? { left: offsets.get(c.key) } : undefined);

  const pool = useMemo(() => data.rows.filter((r) => (r.returned ? !excludeReturned.has(r.row_uid ?? "") : !excludeIds.has(r.id))), [data.rows, excludeIds, excludeReturned]);
  const visible = useMemo(() => {
    const draft = extraRows.filter((r) => !pool.some((p) => p.row_uid === r.row_uid));
    let all = [...draft, ...pool];
    const col = sort ? cols.find((c) => c.key === sort.key) : undefined;
    if (sort && col) all = [...all].sort((a, b) => (sortValue(col, a) < sortValue(col, b) ? -1 : sortValue(col, a) > sortValue(col, b) ? 1 : 0) * sort.dir);
    return all;
  }, [pool, extraRows, sort, cols]);
  const placedHere = data.rows.length - pool.length;
  const returnedCount = visible.filter((r) => r.returned).length;
  const input = "rounded-md border border-slate-200 bg-white px-2 py-1 text-xs";

  return (
    <section className={`rounded-2xl border border-slate-200 bg-white shadow-sm ${fill ? "flex min-h-0 flex-[2] flex-col" : ""}`} data-testid="unplanned-panel">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
        <div>
          <h2 className="text-sm font-bold text-slate-900">Chưa lên KH (Unplanned)</h2>
          <p className="text-[11px] text-slate-500">
            {num(visible.length)} PO{returnedCount ? ` (${returnedCount} trả về từ kế hoạch)` : ""}
            {placedHere ? ` · ${placedHere} đã kéo vào bản nháp` : ""}
            {loading ? " · đang tải..." : ""} · {editable ? "kéo dòng lên lưới Planned để lên kế hoạch; kéo dòng Planned xuống đây để trả về" : "vào Edit Mode để kéo thả"}
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
        {chooser.node}
      </div>

      <div
        className={`pg overflow-auto ${fill ? "min-h-0 flex-1" : "max-h-[38vh]"} ${light ? "pg-light" : ""} ${dropOver ? "pg-zone-over" : ""}`}
        data-testid="unplanned-grid"
        onDragOver={(e) => {
          if (editable && drag.current?.kind === "row") {
            e.preventDefault();
            setDropOver(true);
          }
        }}
        onDragLeave={() => setDropOver(false)}
        onDrop={(e) => {
          setDropOver(false);
          if (editable && drag.current?.kind === "row") {
            e.preventDefault();
            const uid = drag.current.uid;
            drag.current = null;
            onDropPlanned(uid);
          }
        }}
      >
        <table style={{ width: CTRL_W + cols.reduce((sum, c) => sum + cw.widthOf(c.key), 0) }}>
          <colgroup>
            <col style={{ width: CTRL_W }} />
            {cols.map((c) => <col key={c.key} style={{ width: cw.widthOf(c.key) }} />)}
          </colgroup>
          <thead>
            <tr className="pg-h1">
              <th className="frozen" style={{ left: 0 }} />
              {cols.map((c) => (
                <th
                  key={c.key}
                  className={`${c.frozen ? "frozen" : ""} ${c.kind === "num" ? "pg-r" : ""}`}
                  style={frozenStyle(c)}
                  onClick={() => setSort((cur) => (cur?.key !== c.key ? { key: c.key, dir: 1 } : cur.dir === 1 ? { key: c.key, dir: -1 } : null))}
                  title="Bấm để sắp xếp"
                >
                  {c.label} {sort?.key === c.key ? (sort.dir === 1 ? "▲" : "▼") : ""}
                  <span className="pg-rz" role="separator" aria-label={`Kéo để đổi độ rộng cột ${c.label}`} onPointerDown={(e) => cw.startResize(c.key, e)} onClick={(e) => e.stopPropagation()} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr
                key={r.returned ? `ret-${r.row_uid}` : r.id}
                className="pg-row"
                style={{ ["--row-bg" as string]: r.returned ? (light ? "#ede9fe" : "#2a2350") : r.factory_assignment === "UNASSIGNED" ? (light ? "#f1f5f9" : "#1a1f33") : undefined }}
                draggable={editable}
                onDragStart={(e) => {
                  e.dataTransfer.setData("text/plain", String(r.id));
                  e.dataTransfer.effectAllowed = "move";
                  drag.current = r.returned ? { kind: "returned", uid: r.row_uid ?? "" } : { kind: "unplanned", id: r.id };
                }}
                onDragEnd={() => (drag.current = null)}
              >
                <td className="frozen pg-ctrl" style={{ left: 0 }}>
                  <span className={editable ? "pg-handle" : "pg-handle pg-off"}>⠿</span>
                  {r.mapping_status === "WARNING" && <span title={r.mapping_note} className="pg-ovr">⚠</span>}
                </td>
                {cols.map((c) => (
                  <td key={c.key} className={`${c.frozen ? "frozen" : ""} ${c.kind === "num" ? "pg-r" : ""}`} style={frozenStyle(c)} title={c.key === "description" ? r.description : undefined}>
                    {c.key === "factory" ? (
                      <>
                        {r.factory_assignment === "KNOWN" ? <span className="pg-chip pg-known">{r.factory_code}</span> : <span className="pg-chip pg-unk">Chưa xác định XN</span>}
                        {r.returned && <span className="pg-chip pg-viol" title="Đã trả về từ kế hoạch">↩</span>}
                      </>
                    ) : c.key === "so" && r.so_number ? (
                      <span className="inline-flex items-center gap-1" title={r.so_description}>
                        <span className="font-mono text-[11px]">{r.so_number}</span>
                        <button type="button" onClick={(e) => { e.stopPropagation(); void navigator.clipboard?.writeText(r.so_number ?? ""); }} className="text-slate-400 hover:text-slate-700" aria-label={`Sao chép ${r.so_number}`} title="Sao chép">⧉</button>
                      </span>
                    ) : (
                      cellText(c, r)
                    )}
                  </td>
                ))}
              </tr>
            ))}
            {visible.length === 0 && (
              <tr>
                <td colSpan={cols.length + 1} style={{ textAlign: "center", padding: 24 }}>Không có PO nào khớp bộ lọc.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
