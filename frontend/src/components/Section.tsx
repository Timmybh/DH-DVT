import { ReactNode } from "react";

interface SectionProps {
  title: string;
  subtitle?: string;
  right?: ReactNode;
  children: ReactNode;
  /** Màu header của widget (Cấu hình Dashboard → Chỉ số theo dõi → Màu header) — tô dải nền header + viền trên, rỗng/undefined thì dùng giao diện mặc định. */
  headerColor?: string | null;
}

export default function Section({ title, subtitle, right, children, headerColor }: SectionProps) {
  const hasColor = !!headerColor;
  return (
    <section className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-2 shadow-sm">
      {/* Thanh dải màu header: dùng div riêng thay vì border-top vì .dvt-dark .border-slate-200{border-color:...!important} sẽ đè border-top-color.
          Tràn ra ngoài đúng 1px (bằng độ dày viền section) để phủ kín góc bo tròn, không chừa khe hở màu viền mặc định. */}
      {hasColor && <div className="absolute h-[4px]" style={{ background: headerColor as string, top: -1, left: -1, right: -1 }} aria-hidden />}
      <div className="mb-1.5 flex items-start justify-between gap-1.5 rounded-lg" style={hasColor ? { background: `${headerColor}1a`, padding: "4px 6px", margin: "-4px -6px 2px" } : undefined}>
        <div>
          <h2 className={`text-sm font-bold ${hasColor ? "" : "text-slate-900"}`} style={hasColor ? { color: headerColor as string } : undefined}>{title}</h2>
          {subtitle && <p className="text-[11px] text-slate-500">{subtitle}</p>}
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "SUCCEEDED"
      ? "bg-green-100 text-green-700"
      : status === "PARTIAL"
        ? "bg-amber-100 text-amber-700"
        : status === "FAILED"
          ? "bg-red-100 text-red-700"
          : "bg-slate-100 text-slate-600";
  return <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${cls}`}>{status}</span>;
}
