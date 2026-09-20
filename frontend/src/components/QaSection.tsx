import { QaSummary } from "../api/client";
import { num } from "../lib/format";
import Section from "./Section";

const FACTORY_COLOR: Record<string, string> = { XN1: "#6366f1", XN2: "#0ea5e9", XN3: "#f59e0b" };

interface Props {
  data: QaSummary;
  onDrill: (category: string) => void;
}

/** QA: Total Defect Count. Dòng = xí nghiệp, cột = nhóm kiểm tra; mỗi ô có số lỗi và thanh so sánh trong cùng nhóm. */
export default function QaSection({ data, onDrill }: Props) {
  const [y, m] = data.month.split("-");
  const cats = data.categories;
  const codes = cats[0]?.by_factory.map((b) => b.code) ?? [];
  const countOf = (cat: (typeof cats)[number], code: string) => cat.by_factory.find((b) => b.code === code)?.count ?? 0;
  const colMax = (cat: (typeof cats)[number]) => Math.max(1, ...cat.by_factory.map((b) => b.count ?? 0));
  const rowTotal = (code: string) => cats.reduce((s, c) => s + (c.connected ? countOf(c, code) : 0), 0);

  return (
    <Section
      title="Chất lượng (QA)"
      subtitle={`Tổng số lỗi (Total Defect Count) tháng ${m}/${y}${data.latest_day ? ` · dữ liệu đến ${new Date(data.latest_day).toLocaleDateString("vi-VN")}` : ""} · bấm tiêu đề cột để xem theo ngày`}
    >
      {!data.has_data ? (
        <p className="text-sm text-slate-500">Chưa có dữ liệu QA từ eGMF — bấm "Đồng bộ ngay" ở Quản trị → Sync Log.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] border-separate border-spacing-y-1.5 text-sm" data-testid="qa-matrix">
            <thead>
              <tr className="text-xs uppercase text-slate-400">
                <th className="w-24 pb-1 text-left font-semibold">Xí nghiệp</th>
                {cats.map((c) => (
                  <th key={c.key} className="pb-1 text-right font-semibold">
                    <button onClick={() => c.connected && onDrill(c.key)} disabled={!c.connected} data-testid={`qa-${c.key}`} className="uppercase hover:text-slate-200 disabled:cursor-default" title={c.connected ? "Xem theo ngày" : "Chưa kết nối"}>
                      {c.label}
                    </button>
                  </th>
                ))}
                <th className="pb-1 text-right font-semibold">Tổng</th>
              </tr>
            </thead>
            <tbody>
              {codes.map((code) => {
                const selected = data.selected === code;
                return (
                  <tr key={code} data-testid={`qa-row-${code}`}>
                    <td className={`rounded-l-lg py-2 pl-2 font-bold ${selected ? "bg-indigo-500/15" : ""}`}>
                      <span className="mr-2 inline-block h-2.5 w-2.5 rounded-sm align-middle" style={{ background: FACTORY_COLOR[code] ?? "#94a3b8" }} />
                      {code}
                    </td>
                    {cats.map((c) => {
                      const v = countOf(c, code);
                      return (
                        <td key={c.key} className={`relative py-2 pr-2 text-right tabular-nums ${selected ? "bg-indigo-500/15" : ""}`} data-testid={`qa-cell-${code}-${c.key}`}>
                          {c.connected && (
                            <span className="absolute inset-y-1 right-0 rounded-l opacity-30" style={{ width: `${(v / colMax(c)) * 100}%`, background: FACTORY_COLOR[code] ?? "#94a3b8" }} aria-hidden />
                          )}
                          <span className="relative font-semibold">{c.connected ? num(v) : "—"}</span>
                        </td>
                      );
                    })}
                    <td className={`rounded-r-lg py-2 pr-2 text-right font-bold tabular-nums ${selected ? "bg-indigo-500/15" : ""}`}>{num(rowTotal(code))}</td>
                  </tr>
                );
              })}
              <tr className="border-t border-slate-200 text-slate-500">
                <td className="pl-2 pt-1 text-xs font-semibold uppercase">Cộng</td>
                {cats.map((c) => (
                  <td key={c.key} className="pr-2 pt-1 text-right text-xs font-bold tabular-nums">{c.connected ? num(c.total) : "—"}</td>
                ))}
                <td className="pr-2 pt-1 text-right text-xs font-bold tabular-nums">{num(cats.reduce((s, c) => s + (c.total ?? 0), 0))}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
