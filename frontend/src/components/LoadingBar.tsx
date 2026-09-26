/** Thanh loading + dòng chú thích, dùng khi Dashboard mở lên và đang tính toán dữ liệu. */
export default function LoadingBar({ text = "Đang tính toán dữ liệu..." }: { text?: string }) {
  return (
    <div className="space-y-2 py-2" role="status" aria-live="polite" data-testid="loading-bar">
      <div className="dvt-loadbar" />
      <p className="text-sm text-slate-500">{text}</p>
    </div>
  );
}
