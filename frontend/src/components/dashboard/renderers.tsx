import { ReactNode } from "react";
import { Drill, RuntimeItem } from "../../api/client";
import { num } from "../../lib/format";
import SpeedGauge from "../SpeedGauge";
import HrSection from "../HrSection";
import OrderKpiSection from "../OrderKpiSection";
import ProgressSection from "../ProgressSection";
import QaSection from "../QaSection";
import RevenueSection from "../RevenueSection";
import Section from "../Section";
import { GoodNewsCard, WarningCard } from "../SignalsSidebar";

/** Hành động drill-down do trang Dashboard cung cấp; renderer không biết gì về DrillDrawer. */
export interface DashActions {
  month: string;
  drillRevenue: (factoryCode: string) => void;
  drillOrder: (kind: "SEWING" | "FG", status: "ON_TIME" | "LATE" | "OVERDUE") => void;
  drillQa: (category: string) => void;
  drillPo: (risk: string) => void;
  drillHr: () => void;
  drillSignal: (d: Drill) => void;
}

type Renderer = (item: RuntimeItem, a: DashActions) => ReactNode;

const FRESHNESS_TEXT: Record<string, string> = { STALE: "Dữ liệu cũ hơn yêu cầu — đồng bộ lại để cập nhật", UNKNOWN: "" };

/** Khung chung: hiển thị trạng thái ERROR / EMPTY / STALE của rule mà không làm hỏng các widget khác. */
export function WidgetShell({ item, children }: { item: RuntimeItem; children: ReactNode }) {
  const { status, message, meta } = item.data;
  if (status === "ERROR") {
    return (
      <div className="rounded-2xl border border-red-300/60 bg-red-500/10 p-4 text-sm" role="alert" data-testid={`widget-error-${item.indicator.indicator_code}`}>
        <p className="font-semibold text-red-700">{item.indicator.indicator_name} — không tính được</p>
        <p className="mt-1 text-xs text-red-600">{message || "Rule bị lỗi"}</p>
      </div>
    );
  }
  return (
    <div className="relative" data-testid={`widget-${item.indicator.indicator_code}`} data-status={status}>
      {status === "STALE" && (
        <p className="mb-1 rounded-lg border border-amber-300/50 bg-amber-500/10 px-3 py-1 text-[11px] text-amber-700" data-testid="stale-marker">
          ⏱ {FRESHNESS_TEXT.STALE}
          {meta.source_last_sync_at ? ` (lần đồng bộ cuối ${new Date(meta.source_last_sync_at).toLocaleString("vi-VN")})` : ""}
        </p>
      )}
      {children}
    </div>
  );
}

function Unsupported({ item }: { item: RuntimeItem }) {
  return (
    <Section title={item.indicator.indicator_name} subtitle="Kiểu hiển thị chưa được hỗ trợ">
      <p className="text-sm text-amber-700" data-testid="unknown-display-type">
        Không có renderer cho kiểu hiển thị "{item.indicator.display_type}" (rule {item.indicator.rule_code}). Chọn kiểu khác trong Cấu hình Dashboard.
      </p>
    </Section>
  );
}

const CUSTOM_COMPONENTS: Record<string, Renderer> = {
  REVENUE_EXECUTIVE_SUMMARY: (item, a) => <RevenueSection data={item.data.payload} onDrill={a.drillRevenue} />,
  PO_RISK_PIPELINE: (item, a) => <ProgressSection data={item.data.payload} onDrill={a.drillPo} />,
  HR_HEADCOUNT: (item, a) => <HrSection data={item.data.payload} onDrill={a.drillHr} />,
};

function KpiCard({ item }: { item: RuntimeItem }) {
  const p = item.data.payload ?? {};
  return (
    <Section title={item.indicator.indicator_name}>
      <p className="text-4xl font-bold tabular-nums text-slate-900">{p.label ?? (typeof p.value === "number" ? num(p.value, 1) : "—")}</p>
      {p.caption && <p className="mt-1 text-xs text-slate-500">{p.caption}</p>}
    </Section>
  );
}

/** Nhóm Gauge theo xí nghiệp (Sản lượng / Hiệu suất / RFT hôm nay): payload {title, unit, items:[{code,name,value,target,pct}]}. */
function GaugeGroup({ item }: { item: RuntimeItem }) {
  const p = item.data.payload ?? {};
  const items: { code: string; name: string; pct: number | null; window?: string | null }[] = p.items ?? [];
  return (
    <Section title={p.title ?? item.indicator.indicator_name}>
      <div className={`grid gap-3 ${items.length > 2 ? "grid-cols-3" : items.length === 2 ? "grid-cols-2" : "grid-cols-1"}`} data-testid={`gauge-group-${item.indicator.indicator_code}`}>
        {items.map((g) => <SpeedGauge key={g.code} label={g.code} pct={g.pct} />)}
      </div>
    </Section>
  );
}

function TextWidget({ item }: { item: RuntimeItem }) {
  const heading = Boolean(item.data.payload?.heading);
  const text = String(item.data.payload?.text ?? "");
  if (item.indicator.indicator_code === "TEXT_HEADING" || heading) {
    return heading ? <h2 className="text-lg font-bold text-slate-900" data-testid="text-heading">{text || " "}</h2> : <p className="whitespace-pre-wrap text-sm text-slate-700">{text}</p>;
  }
  return (
    <Section title={item.indicator.indicator_name}>
      <p className="whitespace-pre-wrap text-sm text-slate-700">{text}</p>
    </Section>
  );
}

function TableWidget({ item }: { item: RuntimeItem }) {
  const p = item.data.payload ?? {};
  const cols: string[] = p.columns ?? [];
  const rows: (string | number | null)[][] = p.rows ?? [];
  return (
    <Section title={item.indicator.indicator_name}>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-xs uppercase text-slate-400">{cols.map((c) => <th key={c} className="py-1.5 pr-3">{c}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-slate-50">{r.map((v, j) => <td key={j} className="py-1.5 pr-3">{v ?? "—"}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

/** Renderer factory: DisplayType → Renderer. Kiểu chưa hỗ trợ rơi về Unsupported thay vì làm sập trang. */
export const RENDERERS: Record<string, Renderer> = {
  CUSTOM_COMPONENT: (item, a) => {
    const key = String(item.indicator.config_json?.component ?? item.indicator.rule_code);
    const r = CUSTOM_COMPONENTS[key];
    return r ? r(item, a) : <Unsupported item={item} />;
  },
  MATRIX: (item, a) => <OrderKpiSection data={item.data.payload} onDrill={a.drillOrder} />,
  BAR_CHART: (item, a) => <QaSection data={item.data.payload} onDrill={a.drillQa} />,
  SIGNAL_LIST: (item, a) =>
    item.data.payload?.zone === "WARN" ? (
      <WarningCard items={item.data.payload.items ?? []} onDrill={a.drillSignal} />
    ) : (
      <GoodNewsCard items={item.data.payload?.items ?? []} onDrill={a.drillSignal} />
    ),
  GAUGE: (item) => <GaugeGroup item={item} />,
  KPI_CARD: (item) => <KpiCard item={item} />,
  COUNTER: (item) => <KpiCard item={item} />,
  STATUS_COUNTER: (item) => <KpiCard item={item} />,
  TEXT: (item) => <TextWidget item={item} />,
  TABLE: (item) => <TableWidget item={item} />,
};

export function renderIndicator(item: RuntimeItem, actions: DashActions): ReactNode {
  const r = RENDERERS[item.indicator.display_type];
  if (item.data.status === "EMPTY" && !r) return <Unsupported item={item} />;
  return <WidgetShell item={item}>{r ? r(item, actions) : <Unsupported item={item} />}</WidgetShell>;
}
