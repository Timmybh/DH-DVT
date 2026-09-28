import { STATUS_VARS, statusLabel, type StatusToken } from "./tokens";

export default function StatusBadge({ status, progressPercent = null, size = "md" }: { status: StatusToken; progressPercent?: number | null; size?: "sm" | "md" }) {
  const v = STATUS_VARS[status];
  const pad = size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-xs";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full font-semibold ${pad}`} style={{ color: v.fg, background: v.bg }} role="status">
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: v.fg }} aria-hidden="true" />
      {statusLabel(status, progressPercent)}
    </span>
  );
}
