import { useEffect, useState } from "react";
import { api, errorMessage } from "../api/client";
import { dateVi, num } from "../lib/format";

export type DrillTarget = { type: "po"; risk: string } | { type: "revenue"; month: string } | { type: "hr" };

interface Props {
  target: DrillTarget | null;
  scope: string;
  onClose: () => void;
}

const RISK_TITLE: Record<string, string> = {
  ALL: "Danh sách PO đã xếp kế hoạch",
  OK: "PO đúng hạn",
  ADVANCE: "PO hoàn thành sớm hơn kế hoạch",
  LATE: "PO có nguy cơ trễ hạn giao",
  MATERIAL: "PO chưa sẵn sàng nguyên phụ liệu",
  UNPLANNED: "PO chưa lên kế hoạch (Chưa lên KH)",
  UNASSIGNED: "PO chưa xác định XN",
  MAPPING: "Dòng có cảnh báo mapping XN (dữ liệu nguồn)",
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Json = any;

export default function DrillDrawer({ target, scope, onClose }: Props) {
  const [data, setData] = useState<Json>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!target) return;
    setData(null);
    setError("");
    setLoading(true);
    const req =
      target.type === "po"
        ? api.get("/dashboard/drill/po", { params: { scope, risk: target.risk } })
        : target.type === "revenue"
          ? api.get("/dashboard/drill/revenue", { params: { scope, month: target.month } })
          : api.get("/dashboard/drill/hr", { params: { scope } });
    req
      .then((r) => setData(r.data))
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setLoading(false));
  }, [target, scope]);

  if (!target) return null;
  const title =
    target.type === "po" ? RISK_TITLE[target.risk] ?? "Chi tiết PO" : target.type === "revenue" ? `Doanh thu theo ngày — ${target.month}` : "Nhân sự theo tổ";

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div className="flex h-full w-full max-w-4xl flex-col bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <h3 className="text-base font-bold text-slate-900">{title}</h3>
            {target.type === "po" && data && (
              <p className="text-xs text-slate-500">
                {num(data.total)} PO{data.total > data.rows.length ? ` · hiển thị ${data.rows.length} dòng đầu` : ""}
              </p>
            )}
          </div>
          <button onClick={onClose} className="rounded-lg px-3 py-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-auto p-5">
          {loading && <p className="text-sm text-slate-500">Đang tải...</p>}
          {error && <p className="text-sm text-red-600">{error}</p>}

          {data && target.type === "po" && (
            <table className="w-full min-w-[720px] text-left text-xs">
              <thead className="sticky top-0 bg-white">
                <tr className="border-b border-slate-200 text-slate-400">
                  <th className="py-2">XN</th>
                  <th>Chuyền</th>
                  <th>PO</th>
                  <th>Khách hàng</th>
                  <th>Mô tả</th>
                  <th className="text-right">SL</th>
                  <th>CHD</th>
                  <th className="text-right">EHD/CHD</th>
                  <th>Ghi chú / lý do</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r: Json, i: number) => (
                  <tr key={i} className="border-b border-slate-50 align-top">
                    <td className={`py-1.5 font-medium ${r.factory === "Chưa xác định XN" ? "text-slate-400" : ""}`}>
                      {r.factory}
                      {r.mapping_status === "WARNING" && <span title="Cảnh báo mapping" className="ml-1 text-amber-500">⚠</span>}
                    </td>
                    <td>{r.line}</td>
                    <td>{r.po_number}</td>
                    <td>{r.customer}</td>
                    <td className="max-w-[200px] truncate" title={r.description}>{r.description}</td>
                    <td className="text-right">{num(r.quantity)}</td>
                    <td>{dateVi(r.chd)}</td>
                    <td className={`text-right font-semibold ${r.gap_days !== null && r.gap_days <= -1 ? "text-red-600" : "text-slate-700"}`}>
                      {r.gap_days === null ? "—" : r.gap_days.toFixed(1)}
                    </td>
                    <td className="max-w-[220px] text-slate-500">{r.reason}</td>
                  </tr>
                ))}
                {data.rows.length === 0 && (
                  <tr>
                    <td colSpan={9} className="py-6 text-center text-slate-400">Không có PO nào.</td>
                  </tr>
                )}
              </tbody>
            </table>
          )}

          {data && target.type === "revenue" && (
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-xs text-slate-400">
                  <th className="py-2">Ngày</th>
                  {data.codes.map((c: string) => (
                    <th key={c} className="text-right">{c} thực hiện</th>
                  ))}
                  <th className="text-right">Tổng thực hiện</th>
                  <th className="text-right">Tổng kế hoạch</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r: Json) => (
                  <tr key={r.date} className="border-b border-slate-50">
                    <td className="py-1.5">{dateVi(r.date)}</td>
                    {data.codes.map((c: string) => (
                      <td key={c} className="text-right text-slate-600">{num(r.factories[c]?.actual)}</td>
                    ))}
                    <td className="text-right font-semibold">{num(r.actual)}</td>
                    <td className="text-right text-slate-500">{num(r.plan)}</td>
                  </tr>
                ))}
                {data.rows.length === 0 && (
                  <tr>
                    <td colSpan={data.codes.length + 3} className="py-6 text-center text-slate-400">Chưa có số liệu doanh thu ngày trong tháng này.</td>
                  </tr>
                )}
              </tbody>
            </table>
          )}

          {data && target.type === "hr" && (
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-xs text-slate-400">
                  <th className="py-2">Xí nghiệp</th>
                  <th>Tổ / chuyền</th>
                  <th className="text-right">Lao động có mặt</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r: Json, i: number) => (
                  <tr key={i} className="border-b border-slate-50">
                    <td className="py-1.5 font-medium">{r.factory}</td>
                    <td>{r.team}</td>
                    <td className="text-right">{num(r.headcount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
