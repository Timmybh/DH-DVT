import { ReactNode } from "react";

interface SectionProps {
  title: string;
  subtitle?: string;
  right?: ReactNode;
  children: ReactNode;
}

export default function Section({ title, subtitle, right, children }: SectionProps) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-bold text-slate-900">{title}</h2>
          {subtitle && <p className="text-xs text-slate-500">{subtitle}</p>}
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
