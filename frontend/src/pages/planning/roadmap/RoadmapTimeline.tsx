import { useEffect, useRef, useState } from "react";
import { Flag } from "lucide-react";
import { categoryVars } from "./tokens";
import MilestoneCard, { type MilestoneCardData } from "./MilestoneCard";

const MONTH_LABEL = (y: number, m: number) => `${String(m).padStart(2, "0")}/${y}`;
/** Bảng màu xoay vòng cho trục thời gian — line/dot sinh động hơn (thuần trình bày, không gắn business rule). */
const DOT_PALETTE = ["#2563eb", "#7c3aed", "#ea580c", "#16a34a", "#db2777", "#0ea5e9", "#dc2626"];
const MAX_CARD_W = 190;
const MIN_CARD_W = 112;
const GAP = 14;
const CARD_H = 150; // chiều cao giả định để canh so le trên/dưới (card có min-height tương ứng)
const CONNECTOR_GAP = 26; // khoảng hở từ trục tới mép card gần nhất

function useContainerWidth<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    const ro = new ResizeObserver((entries) => setW(entries[0].contentRect.width));
    ro.observe(el);
    setW(el.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

interface Placed { m: MilestoneCardData; tier: 0 | 1; idealCx: number; actualLeft: number; actualCx: number }

/** WF-01: dot trục + card cùng hệ toạ độ theo ngày thật, card so le trên/dưới trục khi mật độ milestone dày
 * (đúng ảnh tham chiếu — không chỉ 1 hàng dưới trục), luôn fit-to-width (không cuộn ngang, không tràn).
 * Edit Mode: kéo tay nắm trên card để dời ngày (onMoveMilestone); kéo thả từ nút "+ Milestone" ở header
 * (placing=true do trang cha điều khiển) để đặt milestone mới lên trục rồi mới điền tên/loại (onPlaceAt). */
export default function RoadmapTimeline({
  milestones, endDate, endLabel, endProgress, rangeStart, rangeEnd, dimFn, onOpen,
  editMode, onMoveMilestone, placing, onPlaceAt, onPlaceCancel,
}: {
  milestones: MilestoneCardData[]; endDate: string | null; endLabel: string; endProgress: number | null;
  rangeStart: Date; rangeEnd: Date; dimFn: (cat: string | null) => boolean; onOpen: (id: number) => void;
  editMode?: boolean; onMoveMilestone?: (id: number, dateIso: string) => void;
  placing?: boolean; onPlaceAt?: (dateIso: string) => void; onPlaceCancel?: () => void;
}) {
  const [containerRef, containerW] = useContainerWidth<HTMLDivElement>();
  const [dragMsId, setDragMsId] = useState<number | null>(null);
  const [dragX, setDragX] = useState<number | null>(null);
  const [ghostX, setGhostX] = useState<number | null>(null);

  const months: { y: number; m: number }[] = [];
  { let y = rangeStart.getFullYear(), m = rangeStart.getMonth() + 1;
    while (y < rangeEnd.getFullYear() || (y === rangeEnd.getFullYear() && m <= rangeEnd.getMonth() + 1)) {
      months.push({ y, m });
      m++; if (m > 12) { m = 1; y++; }
    }
  }
  const totalMs = rangeEnd.getTime() - rangeStart.getTime() || 1;
  const pctOf = (d: Date) => Math.max(0, Math.min(1, (d.getTime() - rangeStart.getTime()) / totalMs));

  const W = Math.max(320, containerW);
  const itemCount = milestones.length + (endDate ? 1 : 0);
  // 2 hàng (so le) nên mỗi hàng chỉ cần chứa ~nửa số card — card được rộng rãi hơn trước
  const perTier = Math.max(1, Math.ceil(itemCount / 2));
  const cardW = Math.min(MAX_CARD_W, Math.max(MIN_CARD_W, W / perTier - GAP));
  const endW = cardW + 10;
  const span = W - endW - cardW / 2 - 8;
  const xOf = (iso: string) => pctOf(new Date(iso)) * span + cardW / 2;
  const dateOfX = (x: number) => {
    const pct = span > 0 ? Math.max(0, Math.min(1, (x - cardW / 2) / span)) : 0;
    return new Date(rangeStart.getTime() + pct * totalMs).toISOString().slice(0, 10);
  };

  const sorted = [...milestones].sort((a, b) => a.target_date.localeCompare(b.target_date));
  const prevRightByTier = [-Infinity, -Infinity];
  let placed: Placed[] = sorted.map((m, i) => {
    const tier = (i % 2) as 0 | 1; // so le trên/dưới theo thứ tự thời gian — milestone sát nhau tự tách hàng
    const idealCx = xOf(m.target_date);
    const idealLeft = idealCx - cardW / 2;
    const actualLeft = Math.max(idealLeft, prevRightByTier[tier] + GAP);
    prevRightByTier[tier] = actualLeft + cardW;
    return { m, tier, idealCx, actualLeft, actualCx: actualLeft + cardW / 2 };
  });
  let endIdealCx = endDate ? xOf(endDate) : W - endW / 2;
  let endActualLeft = Math.max(endIdealCx - endW / 2, Math.max(prevRightByTier[0], prevRightByTier[1]) + GAP, W - endW);
  let endActualCx = endActualLeft + endW / 2;
  const total = endDate ? endActualLeft + endW : Math.max(prevRightByTier[0], prevRightByTier[1]);

  // Vẫn tràn dù đã chia hàng + thu nhỏ tối đa (mật độ cực dày) → nén đều toạ độ để CHẮC CHẮN không tràn khỏi khung.
  if (containerW > 0 && total > W) {
    const scale = W / total;
    placed = placed.map((p) => ({ ...p, idealCx: p.idealCx * scale, actualLeft: p.actualLeft * scale, actualCx: p.actualCx * scale }));
    endIdealCx *= scale; endActualLeft *= scale; endActualCx *= scale;
  }

  const axisY = CARD_H + CONNECTOR_GAP; // trục nằm giữa: hàng "trên" phía trên, hàng "dưới" phía dưới
  const totalH = axisY + CONNECTOR_GAP + CARD_H;

  // Kéo tay nắm trên 1 card đang có để dời ngày — track bằng document listener, chỉ commit khi thả chuột.
  const startDrag = (id: number) => (e: React.MouseEvent) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setDragMsId(id);
    setDragX(Math.max(0, Math.min(W, e.clientX - rect.left)));
    const onMove = (ev: MouseEvent) => setDragX(Math.max(0, Math.min(W, ev.clientX - rect.left)));
    const onUp = (ev: MouseEvent) => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      const x = Math.max(0, Math.min(W, ev.clientX - rect.left));
      setDragMsId(null); setDragX(null);
      onMoveMilestone?.(id, dateOfX(x));
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  // Kéo thả từ nút "+ Milestone" ở header (trang cha bật `placing` khi mousedown) — thả trong vùng trục thì đặt milestone mới tại đúng ngày đó.
  useEffect(() => {
    if (!placing) return;
    const onMove = (ev: MouseEvent) => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      setGhostX(Math.max(0, Math.min(W, ev.clientX - rect.left)));
    };
    const onUp = (ev: MouseEvent) => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      setGhostX(null);
      const rect = containerRef.current?.getBoundingClientRect();
      const inside = !!rect && ev.clientX >= rect.left && ev.clientX <= rect.right && ev.clientY >= rect.top - 60 && ev.clientY <= rect.bottom + 60;
      if (!inside || !rect) { onPlaceCancel?.(); return; }
      onPlaceAt?.(dateOfX(Math.max(0, Math.min(W, ev.clientX - rect.left))));
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => { document.removeEventListener("mousemove", onMove); document.removeEventListener("mouseup", onUp); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placing, W]);

  const Connector = ({ idealCx, actualCx, tier, color }: { idealCx: number; actualCx: number; tier: 0 | 1; color: string }) => {
    const midY = tier === 0 ? axisY - CONNECTOR_GAP * 0.55 : axisY + CONNECTOR_GAP * 0.55;
    const y1 = axisY, y2 = tier === 0 ? axisY - CONNECTOR_GAP : axisY + CONNECTOR_GAP;
    return <path d={`M ${idealCx} ${y1} L ${idealCx} ${midY} L ${actualCx} ${midY} L ${actualCx} ${y2}`} fill="none" stroke={color} strokeWidth={1.75} strokeOpacity={0.65} strokeLinecap="round" strokeLinejoin="round" />;
  };

  return (
    <div ref={containerRef} className="relative w-full" style={{ height: containerW > 0 ? totalH : 1 }} data-testid="rm-timeline">
      {containerW > 0 && (
        <>
          {/* trục gradient nhiều màu ở GIỮA — card so le trên (tier 0) / dưới (tier 1) quanh trục */}
          <div className="absolute left-0 right-0" style={{ top: axisY - 5, height: 10 }}>
            <div className="absolute left-0 right-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full" style={{ background: `linear-gradient(90deg, ${DOT_PALETTE.join(",")})` }} />
            {months.map((mo, i) => (
              <div key={`${mo.y}-${mo.m}`} className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2" style={{ left: xOf(`${mo.y}-${String(mo.m).padStart(2, "0")}-01`) }}>
                <span className="block h-3.5 w-3.5 rounded-full border-[3px] bg-white shadow" style={{ borderColor: DOT_PALETTE[i % DOT_PALETTE.length] }} />
              </div>
            ))}
          </div>
          {months.map((mo) => (
            <span key={`lbl-${mo.y}-${mo.m}`} className="absolute -translate-x-1/2 whitespace-nowrap text-[10px] font-medium" style={{ left: xOf(`${mo.y}-${String(mo.m).padStart(2, "0")}-01`), top: axisY + 10, color: "var(--rm-text-muted)" }}>{MONTH_LABEL(mo.y, mo.m)}</span>
          ))}

          <svg className="absolute left-0 top-0" style={{ width: W, height: totalH, overflow: "visible" }} aria-hidden="true">
            {placed.map(({ m, tier, idealCx, actualCx }) => <Connector key={m.id} idealCx={idealCx} actualCx={actualCx} tier={tier} color={categoryVars(m.category_name).fg} />)}
            {endDate && <Connector idealCx={endIdealCx} actualCx={endActualCx} tier={1} color="var(--rm-status-ontrack)" />}
          </svg>

          {/* card hàng trên: neo mép DƯỚI sát trục */}
          {placed.filter((p) => p.tier === 0).map(({ m, actualLeft }) => {
            const isDragging = dragMsId === m.id && dragX !== null;
            const left = isDragging ? Math.max(0, Math.min(W - cardW, dragX! - cardW / 2)) : actualLeft;
            return (
              <div key={m.id} className="absolute" style={{ left, width: cardW, top: axisY - CONNECTOR_GAP - CARD_H, height: CARD_H, zIndex: isDragging ? 20 : undefined }}>
                <MilestoneCard m={m} onClick={() => onOpen(m.id)} dim={dimFn(m.category_name)} compact={cardW < 160} editMode={editMode} dragging={isDragging} onDragStart={startDrag(m.id)} />
              </div>
            );
          })}
          {/* card hàng dưới: neo mép TRÊN sát trục */}
          {placed.filter((p) => p.tier === 1).map(({ m, actualLeft }) => {
            const isDragging = dragMsId === m.id && dragX !== null;
            const left = isDragging ? Math.max(0, Math.min(W - cardW, dragX! - cardW / 2)) : actualLeft;
            return (
              <div key={m.id} className="absolute" style={{ left, width: cardW, top: axisY + CONNECTOR_GAP, height: CARD_H, zIndex: isDragging ? 20 : undefined }}>
                <MilestoneCard m={m} onClick={() => onOpen(m.id)} dim={dimFn(m.category_name)} compact={cardW < 160} editMode={editMode} dragging={isDragging} onDragStart={startDrag(m.id)} />
              </div>
            );
          })}
          {dragMsId !== null && dragX !== null && (
            <div className="pointer-events-none absolute rounded-full px-2 py-0.5 text-[10px] font-semibold text-white" style={{ left: Math.max(0, Math.min(W - 60, dragX - 30)), top: axisY - 10, background: "var(--rm-text)" }}>
              {dateOfX(dragX).split("-").reverse().slice(0, 2).join("/")}
            </div>
          )}
          {placing && ghostX !== null && (
            <>
              <div className="pointer-events-none absolute top-0 w-px" style={{ left: ghostX, height: totalH, background: "var(--rm-cat-dx)", opacity: 0.6 }} />
              <div className="pointer-events-none absolute flex h-4 w-4 -translate-x-1/2 items-center justify-center rounded-full border-2 border-white" style={{ left: ghostX, top: axisY - 7, background: "var(--rm-cat-dx)" }} />
              <div className="pointer-events-none absolute -translate-x-1/2 rounded-full px-2 py-0.5 text-[10px] font-semibold text-white" style={{ left: ghostX, top: axisY - 32, background: "var(--rm-cat-dx)" }}>
                {dateOfX(ghostX).split("-").reverse().slice(0, 2).join("/")}
              </div>
            </>
          )}
          {endDate && (
            <div className="absolute" style={{ left: endActualLeft, width: endW, top: axisY + CONNECTOR_GAP }}>
              <div className="rounded-[var(--rm-radius-md)] p-3.5 text-white shadow-lg" style={{ background: "linear-gradient(135deg, var(--rm-status-ontrack), #0d9488)" }}>
                <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-white/85"><Flag size={14} />Kết thúc roadmap</div>
                <div className="mt-1 text-sm font-bold">{MONTH_LABEL(new Date(endDate).getFullYear(), new Date(endDate).getMonth() + 1)}</div>
                <div className="text-[11px] text-white/80">{endLabel}</div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/25"><div className="h-full rounded-full bg-white" style={{ width: `${endProgress ?? 0}%` }} /></div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
