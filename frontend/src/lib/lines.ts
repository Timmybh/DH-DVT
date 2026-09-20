export const MAX_LOOSE_LINES = 4; // dồn lẻ tối đa 4 chuyền; muốn nhiều hơn phải dồn TẤT CẢ chuyền của xí nghiệp

/** <= 4 chuyền: "4 + 5 + 9". Nhiều hơn: gộp dải số liên tiếp, tất cả chuyền -> "1:18". Khớp với backend `format_lines`. */
export function formatLines(lines: string[]): string {
  if (lines.length <= MAX_LOOSE_LINES) return lines.join(" + ");
  const nums = lines.filter((l) => /^\d+$/.test(l)).map(Number).sort((a, b) => a - b);
  const others = lines.filter((l) => !/^\d+$/.test(l)).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const parts: string[] = [];
  for (let i = 0; i < nums.length; ) {
    let j = i;
    while (j + 1 < nums.length && nums[j + 1] === nums[j] + 1) j++;
    parts.push(i === j ? String(nums[i]) : `${nums[i]}:${nums[j]}`);
    i = j + 1;
  }
  return [...parts, ...others].join(" + ");
}

export const sortLines = (ls: string[]): string[] => [...ls].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

/** Có phủ hết mọi chuyền của xí nghiệp không (>= 2 chuyền)? */
export const coversAll = (lines: string[], all: string[]): boolean => all.length > 1 && all.every((l) => lines.includes(l));
