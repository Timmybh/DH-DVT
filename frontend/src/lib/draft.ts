import { PlanRowDto, UnplannedDto } from "../api/client";

// Thao tác trên Draft State (khớp với engine backend `apply_ops`)
export type Op =
  | { type: "ADD_FROM_UNPLANNED"; tempRowId: string; sourceId: number; factory: string; line: string; afterRowUid: string | null }
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
): DraftRow[] {
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
        warehouse_date: null, chd: src.chd, note: src.note, extra: {}, _flag: "NEW",
      };
      byUid.set(uid, row);
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
      }
      out.push(r);
    });
  }
  return out;
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
