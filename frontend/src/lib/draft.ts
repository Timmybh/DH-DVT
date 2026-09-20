import { PlanRowDto, UnplannedDto } from "../api/client";
import { formatLines } from "./lines";

// Thao tác trên Draft State (khớp với engine backend `apply_ops`)
export type Op =
  | { type: "ADD_FROM_UNPLANNED"; tempRowId: string; sourceId: number; factory: string; line: string; afterRowUid: string | null }
  | { type: "UNPLAN"; rowUid: string }
  | { type: "RECALC_LANE"; factory: string; line: string; fromRowUid?: string }
  | { type: "SET_LINES"; rowUid: string; lines: string[]; capacity?: number; all?: boolean }
  | { type: "MERGE_LINES"; rowUids: string[]; primaryUid: string; all?: boolean }
  | { type: "SPLIT_LINES"; rowUid: string; lines?: string[]; newLines?: string[]; newAll?: boolean; effectiveDate: string; quantity: number; tempRowId: string }
  | { type: "SET_TRANSFER"; rowUid: string; toLines?: string[]; effectiveDate?: string; plannedRemainingQty?: number | null; clear?: boolean }
  | { type: "ADD_RETURNED"; rowUid: string; factory: string; line: string; afterRowUid: string | null }
  | { type: "MOVE"; rowUid: string; factory: string; line: string; afterRowUid: string | null }
  | { type: "EDIT_FIELD"; rowUid: string; field: string; value: unknown }
  | { type: "RETURN_TO_AUTO_CALC"; rowUid: string; field: string };

export interface DraftRow extends PlanRowDto {
  _flag?: "NEW" | "MOVED" | "EDITED";
}

export const CALCULATED_FIELDS = ["total_day", "begin_prod_date", "end_prod_date", "warehouse_date"];

export const newTempId = (): string => `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
export const tempUid = (tempRowId: string): string => "D" + tempRowId.replace(/\W/g, "").slice(0, 30);
export const laneId = (xn: string, line: string): string => `${xn}|${line}`;

const cloneRow = (r: PlanRowDto): DraftRow => ({ ...r, extra: JSON.parse(JSON.stringify(r.extra ?? {})) });

function insertAfter(lane: DraftRow[], row: DraftRow, afterUid: string | null) {
  if (afterUid === null) {
    lane.unshift(row);
    return;
  }
  const idx = lane.findIndex((r) => r.row_uid === afterUid);
  if (idx < 0) lane.push(row);
  else lane.splice(idx + 1, 0, row);
}

/** Bản sao phía client của apply_ops để hiển thị Draft; ngày tự tính của dòng mới lấy từ kết quả Recheck (computed). */
export function applyOpsLocal(
  base: PlanRowDto[],
  unplanned: Map<number, UnplannedDto>,
  ops: Op[],
  computed: Map<string, PlanRowDto>,
  returnedSnap: Map<string, PlanRowDto> = new Map(),
): { rows: DraftRow[]; returned: DraftRow[] } {
  const returned: DraftRow[] = []; // dòng bị trả về Unplanned trong bản nháp này (chưa Commit)
  const lanes = new Map<string, DraftRow[]>();
  const byUid = new Map<string, DraftRow>();
  const put = (r: DraftRow) => {
    const k = laneId(r.factory_code, r.primary_line);
    if (!lanes.has(k)) lanes.set(k, []);
    lanes.get(k)!.push(r);
    byUid.set(r.row_uid, r);
  };
  [...base].sort((a, b) => a.sequence - b.sequence).forEach((r) => put(cloneRow(r)));

  const take = (r: DraftRow) => {
    const lane = lanes.get(laneId(r.factory_code, r.primary_line));
    if (lane) lane.splice(lane.indexOf(r), 1);
  };
  const place = (r: DraftRow, afterUid: string | null) => {
    const k = laneId(r.factory_code, r.primary_line);
    if (!lanes.has(k)) lanes.set(k, []);
    insertAfter(lanes.get(k)!, r, afterUid);
  };

  for (const op of ops) {
    if (op.type === "ADD_FROM_UNPLANNED") {
      const src = unplanned.get(op.sourceId);
      if (!src) continue;
      const uid = tempUid(op.tempRowId);
      const row: DraftRow = {
        row_uid: uid, sequence: 0, origin: "DRAFT_NEW", source_key: src.source_key, source_plan_row_id: src.id,
        factory_code: op.factory, primary_line: op.line, line_raw: op.line, line_assignments: [op.line], transfer: null,
        po_number: src.po_number, style_cc: src.style_cc, model_code: src.model_code, description: src.description,
        customer: src.customer, sport: src.sport, season: src.season, quantity: src.quantity, capacity: src.capacity,
        total_day: src.capacity ? src.quantity / src.capacity : null, begin_prod_date: null, end_prod_date: null,
        warehouse_date: null, chd: src.chd, note: src.note, extra: {}, _flag: "NEW", ref: src.ref,
      };
      byUid.set(uid, row);
      place(row, op.afterRowUid);
    } else if (op.type === "SET_LINES") {
      const row = byUid.get(op.rowUid);
      if (!row) continue;
      const lines = [...new Set(op.lines.map((x) => x.trim()).filter(Boolean))];
      if (!lines.length) continue;
      take(row);
      row.line_assignments = lines;
      row.line_raw = formatLines(lines);
      row.transfer = null;
      row.primary_line = lines[0];
      if (op.capacity) row.capacity = op.capacity;
      row._flag = row._flag ?? "EDITED";
      const lane = lanes.get(laneId(row.factory_code, row.primary_line)) ?? [];
      place(row, lane[lane.length - 1]?.row_uid ?? null);
    } else if (op.type === "MERGE_LINES") {
      const group = op.rowUids.map((u) => byUid.get(u)).filter((r): r is DraftRow => !!r);
      const keep = byUid.get(op.primaryUid);
      if (!keep || group.length < 2) continue;
      const lines: string[] = [];
      [keep, ...group.filter((r) => r !== keep)].forEach((r) => r.line_assignments.forEach((l) => !lines.includes(l) && lines.push(l)));
      const others = group.filter((r) => r !== keep);
      const workers = group.map((r) => r.ref?.worker ?? 0);
      keep.quantity = group.reduce((s, r) => s + (r.quantity ?? 0), 0);
      if (group.every((r) => r.capacity)) keep.capacity = group.reduce((s, r) => s + (r.capacity ?? 0), 0);
      if (workers.some(Boolean)) keep.ref = { ...(keep.ref ?? {}), worker: workers.reduce((s, w) => s + w, 0) };
      keep.line_assignments = lines;
      keep.line_raw = formatLines(lines);
      keep.transfer = null;
      keep._flag = keep._flag ?? "EDITED";
      others.forEach((r) => {
        take(r);
        byUid.delete(r.row_uid);
      });
    } else if (op.type === "SPLIT_LINES" && (op.newLines?.length || op.newAll)) {
      // Tách SANG chuyền khác: dòng gốc giữ chuyền cũ, dòng mới chạy trên các chuyền chọn (hiển thị tạm; server tính chính xác khi Recheck)
      const row = byUid.get(op.rowUid);
      if (!row || !op.newLines?.length || !(op.quantity > 0 && op.quantity < row.quantity)) continue;
      const uid = tempUid(op.tempRowId);
      const worker = row.ref?.worker;
      const perLine = row.line_assignments.length || 1;
      const fresh: DraftRow = {
        ...cloneRow(row), row_uid: uid, sequence: 0, origin: "DRAFT_NEW", transfer: null, line_assignments: op.newLines, line_raw: formatLines(op.newLines), primary_line: op.newLines[0],
        quantity: op.quantity, capacity: row.capacity ? (row.capacity / perLine) * op.newLines.length : null, begin_prod_date: op.effectiveDate, end_prod_date: null, warehouse_date: null, total_day: null,
        ref: worker ? { ...(row.ref ?? {}), worker: Math.round((worker / perLine) * op.newLines.length * 10) / 10 } : row.ref, _flag: "NEW",
      };
      row.quantity -= op.quantity;
      row._flag = row._flag ?? "EDITED";
      byUid.set(uid, fresh);
      const laneNew = lanes.get(laneId(fresh.factory_code, fresh.primary_line)) ?? [];
      place(fresh, laneNew[laneNew.length - 1]?.row_uid ?? null);
    } else if (op.type === "SPLIT_LINES") {
      const row = byUid.get(op.rowUid);
      if (!row) continue;
      const take2 = (op.lines ?? []).filter((l) => row.line_assignments.includes(l));
      const stay = row.line_assignments.filter((l) => !take2.includes(l));
      if (!take2.length || !stay.length || !(op.quantity > 0 && op.quantity < row.quantity)) continue;
      const share = take2.length / row.line_assignments.length; // hiển thị tạm; kết quả chính xác do server tính khi Recheck
      const uid = tempUid(op.tempRowId);
      const worker = row.ref?.worker;
      const fresh: DraftRow = {
        ...cloneRow(row), row_uid: uid, sequence: 0, origin: "DRAFT_NEW", transfer: null, line_assignments: take2, line_raw: formatLines(take2), primary_line: take2[0],
        quantity: op.quantity, capacity: row.capacity ? row.capacity * share : null, begin_prod_date: op.effectiveDate, end_prod_date: null, warehouse_date: null, total_day: null,
        ref: worker ? { ...(row.ref ?? {}), worker: Math.round(worker * share * 10) / 10 } : row.ref, _flag: "NEW",
      };
      take(row);
      row.quantity -= op.quantity;
      row.capacity = row.capacity ? row.capacity * (1 - share) : null;
      if (worker) row.ref = { ...(row.ref ?? {}), worker: Math.round(worker * (1 - share) * 10) / 10 };
      row.line_assignments = stay;
      row.line_raw = formatLines(stay);
      row.primary_line = stay[0];
      row._flag = row._flag ?? "EDITED";
      const laneOld = lanes.get(laneId(row.factory_code, row.primary_line)) ?? [];
      place(row, laneOld[laneOld.length - 1]?.row_uid ?? null);
      byUid.set(uid, fresh);
      const laneNew = lanes.get(laneId(fresh.factory_code, fresh.primary_line)) ?? [];
      place(fresh, laneNew[laneNew.length - 1]?.row_uid ?? null);
    } else if (op.type === "SET_TRANSFER") {
      const row = byUid.get(op.rowUid);
      if (!row) continue;
      const current = row.line_assignments.join(" + ");
      if (op.clear) {
        row.transfer = null;
        row.line_raw = current;
      } else {
        const to = [...new Set((op.toLines ?? []).map((x) => x.trim()).filter(Boolean))].join(" + ");
        if (!to) continue;
        row.transfer = { from: current, to, effective_date: op.effectiveDate || null, planned_remaining_qty: op.plannedRemainingQty ?? null, status: "PLANNED" };
        row.line_raw = `${current} ==> ${to}`;
      }
      row._flag = row._flag ?? "EDITED";
    } else if (op.type === "UNPLAN") {
      const row = byUid.get(op.rowUid);
      if (!row) continue;
      take(row);
      byUid.delete(op.rowUid);
      returned.push(row);
    } else if (op.type === "ADD_RETURNED") {
      const idx = returned.findIndex((r) => r.row_uid === op.rowUid);
      const snap = idx >= 0 ? returned.splice(idx, 1)[0] : returnedSnap.get(op.rowUid);
      if (!snap) continue;
      const row: DraftRow = { ...cloneRow(snap), factory_code: op.factory, primary_line: op.line, line_raw: op.line, line_assignments: [op.line], transfer: null, _flag: "MOVED" };
      byUid.set(row.row_uid, row);
      place(row, op.afterRowUid);
    } else if (op.type === "MOVE") {
      const row = byUid.get(op.rowUid);
      if (!row) continue;
      take(row);
      if (row.factory_code !== op.factory || row.primary_line !== op.line) {
        row.factory_code = op.factory;
        row.primary_line = op.line;
        row.line_raw = op.line;
        row.line_assignments = [op.line];
      }
      row._flag = row._flag ?? "MOVED";
      place(row, op.afterRowUid);
    } else if (op.type === "EDIT_FIELD") {
      const row = byUid.get(op.rowUid);
      if (!row) continue;
      const rec = row as unknown as Record<string, unknown>;
      if (CALCULATED_FIELDS.includes(op.field)) {
        row.extra.overrides = row.extra.overrides ?? {};
        row.extra.overrides[op.field] ??= { source: "OVERRIDE", calculated: rec[op.field] };
      }
      if (op.field === "transfer_effective_date" && row.transfer) row.transfer = { ...row.transfer, effective_date: (op.value as string) || null };
      else rec[op.field] = op.value === "" ? null : op.value;
      row._flag = row._flag ?? "EDITED";
    } else if (op.type === "RETURN_TO_AUTO_CALC") {
      const row = byUid.get(op.rowUid);
      if (!row) continue;
      if (row.extra.overrides) delete row.extra.overrides[op.field];
      if (op.field === "total_day") row.total_day = row.capacity ? row.quantity / row.capacity : null;
      row._flag = row._flag ?? "EDITED";
    }
  }

  const out: DraftRow[] = [];
  for (const [, lane] of [...lanes.entries()].sort()) {
    lane.forEach((r, i) => {
      r.sequence = i + 1;
      const c = computed.get(r.row_uid);
      if (c) {
        // kết quả tính của server (ngày vào chuyền/may xong, override) cho các dòng bị thao tác
        r.begin_prod_date = c.begin_prod_date;
        r.end_prod_date = c.end_prod_date;
        r.warehouse_date = c.warehouse_date;
        r.total_day = c.total_day;
        r.extra = c.extra;
        r.calc = c.calc;
      }
      out.push(r);
    });
  }
  return { rows: out, returned };
}

const KEY = "dvt_planning_draft";
export interface SavedDraft {
  baseVersionId: number;
  ops: Op[];
  revision: number;
  savedAt: string;
}

export function saveDraft(d: SavedDraft | null): void {
  try {
    if (!d || d.ops.length === 0) localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, JSON.stringify(d));
  } catch {
    /* bỏ qua lỗi lưu cục bộ — không chặn Planning */
  }
}

export function loadDraft(): SavedDraft | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as SavedDraft) : null;
  } catch {
    return null;
  }
}
