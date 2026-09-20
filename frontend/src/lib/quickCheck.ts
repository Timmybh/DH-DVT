import { CapDef, refRowCapacity } from "./capacityRef";
import { DraftRow, Op } from "./draft";
import { buildLanes, rowLines } from "./lanes";

/** Kiểm tra nhẹ theo từng dòng: chỉ các dòng người dùng tự gõ ngày bắt đầu / ngày kết thúc / năng suất, so với dòng liền trước và liền sau
 *  trong cùng chuyền. Chạy tức thì trên client; KHÔNG thay Recheck All Plan (thủ công, nặng hơn — người dùng tự quyết thời điểm). */
export const QUICK_FIELDS = ["begin_prod_date", "end_prod_date", "capacity"];
export const CAPACITY_TOLERANCE = 0.3; // lệch > 30% so với năng suất tham chiếu (đích danh mã hàng, nếu không có thì bình quân của chuyền) thì cảnh báo

export interface QuickIssue {
  row_uid: string;
  severity: "ERROR" | "WARNING";
  column: string;
  code: string;
  message: string;
}

const dmy = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("vi-VN");
const label = (r: DraftRow) => `PO ${r.po_number || r.row_uid}`;

export function touchedRowUids(ops: Op[]): Set<string> {
  const out = new Set<string>();
  for (const o of ops) if (o.type === "EDIT_FIELD" && QUICK_FIELDS.includes(o.field)) out.add(o.rowUid);
  return out;
}

export function quickCheck(rows: DraftRow[], touched: Set<string>, capDefs: CapDef[] = []): QuickIssue[] {
  if (!touched.size) return [];
  const lanes = buildLanes(rows); // lane ảo: dòng nhiều chuyền có mặt ở mọi lane của nó

  const out: QuickIssue[] = [];
  for (const uid of touched) {
    const cur = rows.find((r) => r.row_uid === uid);
    if (!cur) continue;
    // dòng trước / dòng sau theo TỪNG chuyền của dòng (không chỉ primary_line)
    const neighbours = rowLines(cur).map((line) => {
      const lane = lanes.get(`${cur.factory_code}|${line}`) ?? [];
      const i = lane.findIndex((r) => r.row_uid === cur.row_uid);
      return { line, prev: i > 0 ? lane[i - 1] : null, next: i >= 0 && i < lane.length - 1 ? lane[i + 1] : null };
    });
    const add = (severity: QuickIssue["severity"], column: string, code: string, message: string) => out.push({ row_uid: uid, severity, column, code, message });

    const b = cur.begin_prod_date, e = cur.end_prod_date;
    if (b && e && b > e) add("ERROR", "begin_prod_date", "DATE_ORDER", `${label(cur)}: ngày bắt đầu ${dmy(b)} sau ngày kết thúc ${dmy(e)}.`);
    for (const { line, prev, next } of neighbours) {
      const where = rowLines(cur).length > 1 ? ` (chuyền ${line})` : "";
      if (b && prev?.end_prod_date && b < prev.end_prod_date) add("WARNING", "begin_prod_date", "LINE_OVERLAP", `${label(cur)}: bắt đầu ${dmy(b)} trước ngày kết thúc của dòng trước (${label(prev)}, ${dmy(prev.end_prod_date)})${where}.`);
      if (e && next?.begin_prod_date && e > next.begin_prod_date) add("WARNING", "end_prod_date", "LINE_OVERLAP_NEXT", `${label(cur)}: kết thúc ${dmy(e)} sau ngày bắt đầu của dòng sau (${label(next)}, ${dmy(next.begin_prod_date)})${where}.`);
    }

    if (cur.capacity && capDefs.length) {
      const ref = refRowCapacity(capDefs, cur);
      if (ref && ref.value > 0) {
        const dev = Math.abs(cur.capacity - ref.value) / ref.value;
        if (dev > CAPACITY_TOLERANCE) {
          const basis = ref.basis === "STYLE" ? "năng suất định nghĩa cho mã hàng" : ref.basis === "LINE_AVG" ? "năng suất bình quân của chuyền" : "năng suất tham chiếu của các chuyền";
          add("WARNING", "capacity", "CAPACITY_VS_REFERENCE", `${label(cur)}: năng suất ${cur.capacity} lệch ${Math.round(dev * 100)}% so với ${basis} trong bảng năng suất (${Math.round(ref.value)}).`);
        }
      }
    }
  }
  return out;
}
