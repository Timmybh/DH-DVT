"""Bộ tính công thức Planning (thuần, không I/O) — handoff §8–10.

Công thức viết kiểu Excel trên MÃ CỘT nghiệp vụ, ví dụ ``BEGIN_PROD_DATE = PREVIOUS_SEQUENCE.END_BEGIN_DATE + 1/9``.
Không dùng ``eval``: chuỗi được phân tích thành cây cú pháp (AST) rồi tính bằng bộ đánh giá riêng.

Giá trị: số (float), chữ (str), ngày = số serial kiểu Excel (float, có phần lẻ), rỗng = ``None``.
Tham chiếu ngữ nghĩa ``PREVIOUS_SEQUENCE.<CỘT>`` = dòng đứng trước theo THỨ TỰ NGHIỆP VỤ trong cùng chuyền, không phải dòng
đang hiển thị phía trên.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable

EXCEL_EPOCH = date(1899, 12, 30)
SEMANTIC_REFS = {"PREVIOUS_SEQUENCE"}
MAX_DEPTH = 64  # loop guard khi giải phụ thuộc động


class FormulaError(ValueError):
    """Lỗi cú pháp / tham chiếu / kiểu / chia cho 0 khi tính công thức."""


def to_serial(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, date):
        return float((value - EXCEL_EPOCH).days)
    return None


def from_serial(serial: float | None) -> date | None:
    return None if serial is None else EXCEL_EPOCH + timedelta(days=int(serial // 1))


# --------------------------------------------------------------------------- phân tích cú pháp
_TOKEN = re.compile(
    r"""\s*(?:
        (?P<num>\d+(?:\.\d+)?)
      | (?P<str>"[^"]*")
      | (?P<id>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)
      | (?P<op><=|>=|<>|[-+*/<>=(),])
    )""",
    re.VERBOSE,
)


@dataclass
class Node:
    kind: str  # num | str | ref | call | bin | neg
    value: Any = None
    args: list["Node"] = field(default_factory=list)


def tokenize(text: str) -> list[tuple[str, str]]:
    pos, out = 0, []
    text = text.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise FormulaError(f"Ký tự không hợp lệ tại vị trí {pos + 1}: '{text[pos:pos + 8]}'")
        kind = m.lastgroup or ""
        out.append((kind, m.group(kind)))
        pos = m.end()
    return out


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.t, self.i = tokens, 0

    def peek(self) -> tuple[str, str] | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self) -> tuple[str, str]:
        tok = self.peek()
        if tok is None:
            raise FormulaError("Công thức kết thúc đột ngột")
        self.i += 1
        return tok

    def expect(self, op: str) -> None:
        kind, val = self.take()
        if kind != "op" or val != op:
            raise FormulaError(f"Thiếu '{op}'")

    def parse(self) -> Node:
        node = self.comparison()
        if self.peek() is not None:
            raise FormulaError(f"Thừa ký tự sau công thức: '{self.peek()[1]}'")
        return node

    def comparison(self) -> Node:
        left = self.additive()
        tok = self.peek()
        if tok and tok[0] == "op" and tok[1] in ("=", "<>", "<", ">", "<=", ">="):
            self.take()
            return Node("bin", tok[1], [left, self.additive()])
        return left

    def additive(self) -> Node:
        node = self.term()
        while (tok := self.peek()) and tok[0] == "op" and tok[1] in "+-":
            self.take()
            node = Node("bin", tok[1], [node, self.term()])
        return node

    def term(self) -> Node:
        node = self.unary()
        while (tok := self.peek()) and tok[0] == "op" and tok[1] in "*/":
            self.take()
            node = Node("bin", tok[1], [node, self.unary()])
        return node

    def unary(self) -> Node:
        tok = self.peek()
        if tok and tok[0] == "op" and tok[1] == "-":
            self.take()
            return Node("neg", None, [self.unary()])
        return self.atom()

    def atom(self) -> Node:
        kind, val = self.take()
        if kind == "num":
            return Node("num", float(val))
        if kind == "str":
            return Node("str", val[1:-1])
        if kind == "op" and val == "(":
            node = self.comparison()
            self.expect(")")
            return node
        if kind == "id":
            nxt = self.peek()
            if nxt and nxt == ("op", "("):
                self.take()
                args: list[Node] = []
                if self.peek() != ("op", ")"):
                    args.append(self.comparison())
                    while self.peek() == ("op", ","):
                        self.take()
                        args.append(self.comparison())
                self.expect(")")
                return Node("call", val.upper(), args)
            return Node("ref", val.upper())
        raise FormulaError(f"Không hiểu '{val}'")


def parse(expression: str) -> Node:
    if not expression or not expression.strip():
        raise FormulaError("Công thức trống")
    return _Parser(tokenize(expression)).parse()


# --------------------------------------------------------------------------- hàm
def _num(v: Any) -> float:
    if v is None or v == "":
        raise FormulaError("Giá trị trống")
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    raise FormulaError(f"'{v}' không phải số")


def _ceiling(x: float) -> float:
    import math

    return float(math.ceil(x - 1e-9))


def _round_half_up(x: float, digits: float = 0) -> float:
    import math

    f = 10 ** int(digits)
    return math.floor(x * f + 0.5) / f


FUNCTIONS: dict[str, tuple[int, int]] = {  # (min, max) số đối số — kiểm tra khi Validate
    "IF": (3, 3), "IFERROR": (2, 2), "AND": (2, 8), "OR": (2, 8), "MAX": (2, 8), "MIN": (2, 8), "ABS": (1, 1),
    "ROUND": (1, 2), "CEILING": (1, 1), "FLOOR": (1, 1), "ISBLANK": (1, 1), "MANUAL": (0, 0),
}


# --------------------------------------------------------------------------- phụ thuộc
@dataclass
class Dependencies:
    columns: set[str] = field(default_factory=set)  # cột của chính dòng
    semantic: set[tuple[str, str]] = field(default_factory=set)  # (PREVIOUS_SEQUENCE, END_BEGIN_DATE)
    functions: set[str] = field(default_factory=set)

    def as_json(self) -> dict:
        return {"columns": sorted(self.columns), "semantic": sorted(f"{a}.{b}" for a, b in self.semantic), "functions": sorted(self.functions)}


def extract_dependencies(node: Node, known_columns: set[str] | None = None) -> Dependencies:
    deps = Dependencies()

    def walk(n: Node) -> None:
        if n.kind == "ref":
            if "." in n.value:
                sem, col = n.value.split(".", 1)
                if sem not in SEMANTIC_REFS:
                    raise FormulaError(f"Tham chiếu ngữ nghĩa '{sem}' không được hỗ trợ (chỉ có {', '.join(sorted(SEMANTIC_REFS))})")
                if known_columns is not None and col not in known_columns:
                    raise FormulaError(f"Cột '{col}' không tồn tại trong danh mục cột")
                deps.semantic.add((sem, col))
            else:
                if known_columns is not None and n.value not in known_columns:
                    raise FormulaError(f"Cột '{n.value}' không tồn tại trong danh mục cột")
                deps.columns.add(n.value)
        elif n.kind == "call":
            if n.value not in FUNCTIONS:
                raise FormulaError(f"Hàm '{n.value}' không được hỗ trợ")
            lo, hi = FUNCTIONS[n.value]
            if not lo <= len(n.args) <= hi:
                raise FormulaError(f"Hàm {n.value} cần {lo}–{hi} đối số, nhận {len(n.args)}")
            deps.functions.add(n.value)
        for a in n.args:
            walk(a)

    walk(node)
    return deps


def detect_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    """graph: cột -> tập cột nó phụ thuộc TRONG CÙNG dòng. Trả đường đi vòng nếu có, ngược lại None.

    Phụ thuộc ngữ nghĩa (PREVIOUS_SEQUENCE) đi qua dòng khác nên không tạo vòng trên cùng ô; nhưng cùng cột tự tham chiếu
    PREVIOUS_SEQUENCE của chính nó là hợp lệ (dòng trước → dòng sau).
    """
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = {}
    stack: list[str] = []

    def dfs(u: str) -> list[str] | None:
        color[u] = GREY
        stack.append(u)
        for v in graph.get(u, ()):
            if color.get(v, WHITE) == GREY:
                return stack[stack.index(v):] + [v]
            if color.get(v, WHITE) == WHITE and (cyc := dfs(v)):
                return cyc
        stack.pop()
        color[u] = BLACK
        return None

    for node in list(graph):
        if color.get(node, WHITE) == WHITE and (cyc := dfs(node)):
            return cyc
    return None


# --------------------------------------------------------------------------- đánh giá
@dataclass
class Context:
    """Nguồn giá trị cho một lần tính. ``get``/``prev`` do runtime cung cấp (đệ quy sang công thức của cột khác)."""

    get: Callable[[str], Any]
    prev: Callable[[str], Any]
    manual: Callable[[], Any] = lambda: None
    depth: int = 0


def evaluate(node: Node, ctx: Context) -> Any:
    k = node.kind
    if k == "num" or k == "str":
        return node.value
    if k == "neg":
        return -_num(evaluate(node.args[0], ctx))
    if k == "ref":
        if "." in node.value:
            _sem, col = node.value.split(".", 1)
            return ctx.prev(col)
        return ctx.get(node.value)
    if k == "bin":
        op = node.value
        a, b = evaluate(node.args[0], ctx), evaluate(node.args[1], ctx)
        if op in ("=", "<>"):
            eq = (a == b) or (a in (None, "") and b in (None, ""))
            return eq if op == "=" else not eq
        if op in ("<", ">", "<=", ">="):
            x, y = _num(a), _num(b)
            return {"<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op]
        x, y = _num(a), _num(b)
        if op == "+":
            return x + y
        if op == "-":
            return x - y
        if op == "*":
            return x * y
        if y == 0:
            raise FormulaError("Chia cho 0")
        return x / y
    if k == "call":
        return _call(node, ctx)
    raise FormulaError(f"Nút không hợp lệ: {k}")


def _call(node: Node, ctx: Context) -> Any:
    name, args = node.value, node.args
    if name == "IF":  # đánh giá lười: chỉ nhánh được chọn
        return evaluate(args[1], ctx) if evaluate(args[0], ctx) else evaluate(args[2], ctx)
    if name == "IFERROR":
        try:
            v = evaluate(args[0], ctx)
            return evaluate(args[1], ctx) if v is None else v
        except FormulaError:
            return evaluate(args[1], ctx)
    if name == "MANUAL":
        return ctx.manual()
    if name == "ISBLANK":
        return evaluate(args[0], ctx) in (None, "")
    vals = [evaluate(a, ctx) for a in args]
    if name == "AND":
        return all(bool(v) for v in vals)
    if name == "OR":
        return any(bool(v) for v in vals)
    nums = [_num(v) for v in vals]
    if name == "MAX":
        return max(nums)
    if name == "MIN":
        return min(nums)
    if name == "ABS":
        return abs(nums[0])
    if name == "CEILING":
        return _ceiling(nums[0])
    if name == "FLOOR":
        import math

        return float(math.floor(nums[0]))
    if name == "ROUND":
        return _round_half_up(nums[0], nums[1] if len(nums) > 1 else 0)
    raise FormulaError(f"Hàm '{name}' không được hỗ trợ")


def compile_expression(expression: str, known_columns: set[str] | None = None) -> tuple[Node, Dependencies]:
    node = parse(expression)
    return node, extract_dependencies(node, known_columns)


def run_case(node: Node, inputs: dict, prev: dict | None = None, manual: Any = None) -> Any:
    """Tính một ca chuẩn: giá trị đầu vào cho từng cột, dòng trước (nếu có) và giá trị nhập tay (MANUAL)."""
    ctx = Context(get=lambda c: inputs.get(c), prev=lambda c: (prev or {}).get(c), manual=lambda: manual)
    return evaluate(node, ctx)
