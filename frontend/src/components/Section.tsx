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
  // Có màu: section bỏ hẳn padding riêng — header tint và dải màu bleed đúng 1px (độ dày border) để sát viền
  // tuyệt đối, không cần "trừ padding rồi cộng lại" (dễ lệch vài px). Phần đệm cho chữ/nội dung chuyển vào
  // 2 wrapper con (header + body) thay vì đặt trên chính section.
  return (
    <section className={`relative overflow-hidden border border-slate-200 bg-white shadow-sm ${hasColor ? "" : "rounded-2xl p-2"}`}>
      {/* Thanh dải màu header: dùng div riêng thay vì border-top vì .dvt-dark .border-slate-200{border-color:...!important} sẽ đè border-top-color.
          Có màu thì bỏ bo góc toàn khung (vuông hết) để dải màu sát viền, không cần né góc cong. */}
      {hasColor && <div className="absolute -inset-x-px -top-px h-[4px]" style={{ background: headerColor as string }} aria-hidden />}
      <div
        className={`mb-1.5 flex items-start justify-between gap-1.5 ${hasColor ? "-mx-px -mt-px" : "rounded-lg"}`}
        style={hasColor ? { background: `${headerColor}1a`, padding: "11px 10px 6px" } : undefined}
      >
        <div>
          <h2 className={`text-sm font-bold ${hasColor ? "" : "text-slate-900"}`} style={hasColor ? { color: headerColor as string } : undefined}>{title}</h2>
          {subtitle && <p className="text-[11px] text-slate-500">{subtitle}</p>}
        </div>
        {right}
      </div>
      <div className={hasColor ? "px-2 pb-2" : undefined}>{children}</div>
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
