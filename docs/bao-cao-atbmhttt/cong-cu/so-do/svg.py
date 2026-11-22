"""Tiện ích vẽ SVG đơn giản cho các sơ đồ của báo cáo."""

from html import escape

FONT = "Liberation Sans, Arial, DejaVu Sans, sans-serif"
MONO = "DejaVu Sans Mono, JetBrains Mono, monospace"
INK = "#1f2a30"
MUTED = "#5b6b73"
LINE = "#33424a"
FILL = "#f3f6f5"
ACCENT = "#0f6e5a"
ACCENT_FILL = "#e3f1ec"
WARN = "#b42318"
WARN_FILL = "#fdecea"
KEY = "#8a5a00"
KEY_FILL = "#fdf3dc"
BLUE = "#1d4f91"
BLUE_FILL = "#e7eef8"


class Svg:
    def __init__(self, width: int, height: int) -> None:
        self.w, self.h = width, height
        self.parts: list[str] = []

    def add(self, s: str) -> None:
        self.parts.append(s)

    def text(self, x: float, y: float, s: str, size: int = 14, anchor: str = "middle",
             color: str = INK, weight: str = "normal", mono: bool = False, italic: bool = False,
             line_gap: float = 1.25, halo: bool = False) -> None:
        lines = s.split("\n")
        family = MONO if mono else FONT
        style = "italic" if italic else "normal"
        first = y - (len(lines) - 1) * size * line_gap / 2
        spans = "".join(
            f'<tspan x="{x}" y="{first + i * size * line_gap:.1f}">{escape(line)}</tspan>'
            for i, line in enumerate(lines)
        )
        extra = ' stroke="#ffffff" stroke-width="5" paint-order="stroke" stroke-linejoin="round"' if halo else ""
        self.add(
            f'<text font-family="{family}" font-size="{size}" fill="{color}" font-weight="{weight}" '
            f'font-style="{style}" text-anchor="{anchor}" dominant-baseline="middle"{extra}>{spans}</text>'
        )

    def rect(self, x: float, y: float, w: float, h: float, label: str = "", fill: str = FILL,
             stroke: str = LINE, size: int = 14, rx: int = 6, weight: str = "normal",
             dash: bool = False, color: str = INK, mono: bool = False, sw: float = 1.4) -> None:
        d = ' stroke-dasharray="6 4"' if dash else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
                 f'stroke="{stroke}" stroke-width="{sw}"{d}/>')
        if label:
            self.text(x + w / 2, y + h / 2, label, size, weight=weight, color=color, mono=mono)

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, label: str, fill: str = FILL,
                stroke: str = LINE, size: int = 13) -> None:
        self.add(f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}" stroke="{stroke}" '
                 f'stroke-width="1.4"/>')
        self.text(cx, cy, label, size)

    def line(self, x1: float, y1: float, x2: float, y2: float, color: str = LINE,
             dash: bool = False, arrow: bool = True, sw: float = 1.4, open_head: bool = False) -> None:
        d = ' stroke-dasharray="6 4"' if dash else ""
        marker = ""
        if arrow:
            marker = f' marker-end="url(#{"open" if open_head else "head"}-{color.strip("#")})"'
        self.add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
                 f'stroke-width="{sw}"{d}{marker}/>')

    def path(self, d: str, color: str = LINE, dash: bool = False, arrow: bool = True,
             sw: float = 1.4, fill: str = "none") -> None:
        da = ' stroke-dasharray="6 4"' if dash else ""
        marker = f' marker-end="url(#head-{color.strip("#")})"' if arrow else ""
        self.add(f'<path d="{d}" fill="{fill}" stroke="{color}" stroke-width="{sw}"{da}{marker}/>')

    def actor(self, cx: float, top: float, label: str, size: int = 13) -> None:
        s = (f'<g stroke="{LINE}" stroke-width="1.6" fill="none">'
             f'<circle cx="{cx}" cy="{top + 9}" r="9" fill="#fff"/>'
             f'<line x1="{cx}" y1="{top + 18}" x2="{cx}" y2="{top + 42}"/>'
             f'<line x1="{cx - 15}" y1="{top + 26}" x2="{cx + 15}" y2="{top + 26}"/>'
             f'<line x1="{cx}" y1="{top + 42}" x2="{cx - 12}" y2="{top + 60}"/>'
             f'<line x1="{cx}" y1="{top + 42}" x2="{cx + 12}" y2="{top + 60}"/></g>')
        self.add(s)
        self.text(cx, top + 76, label, size)

    def render(self) -> str:
        colors = {INK, LINE, ACCENT, WARN, KEY, BLUE, MUTED}
        markers = "".join(
            f'<marker id="head-{c.strip("#")}" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
            f'<marker id="open-{c.strip("#")}" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="9" markerHeight="9" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10" fill="none" stroke="{c}" stroke-width="1.5"/></marker>'
            for c in colors
        )
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                f'viewBox="0 0 {self.w} {self.h}"><defs>{markers}</defs>'
                f'<rect width="100%" height="100%" fill="#ffffff"/>{"".join(self.parts)}</svg>')


class Sequence:
    """Biểu đồ tuần tự: các đối tượng theo cột, thông điệp theo hàng."""

    def __init__(self, participants: list[tuple[str, str]], width: int = 1200,
                 top: int = 20, row: int = 44) -> None:
        self.names = [p[0] for p in participants]
        self.kinds = {p[0]: p[1] for p in participants}
        self.width = width
        self.top = top
        self.row = row
        margin = 90
        step = (width - 2 * margin) / max(1, len(participants) - 1)
        self.x = {name: margin + i * step for i, name in enumerate(self.names)}
        self.items: list[tuple] = []

    def msg(self, a: str, b: str, label: str, reply: bool = False, color: str = INK) -> None:
        self.items.append(("msg", a, b, label, reply, color))

    def self_msg(self, a: str, label: str, color: str = INK) -> None:
        self.items.append(("self", a, label, color))

    def note(self, a: str, b: str, label: str, fill: str = KEY_FILL, stroke: str = KEY) -> None:
        self.items.append(("note", a, b, label, fill, stroke))

    def group(self, label: str) -> None:
        self.items.append(("group", label))

    def end_group(self) -> None:
        self.items.append(("end",))

    def render(self) -> str:
        head_h = 92
        y = self.top + head_h + 24
        rows: list[tuple[tuple, float, float]] = []
        for item in self.items:
            if item[0] == "self":
                h = self.row + 22
            elif item[0] == "note":
                h = 16 + 18 * (item[3].count("\n") + 1) + 10
            elif item[0] == "msg":
                h = self.row + 16 * item[3].count("\n")
            elif item[0] == "group":
                h = 34
            else:
                h = 16
            rows.append((item, y, h))
            y += h
        height = int(y + 24 + head_h)
        svg = Svg(self.width, height)
        bottom = y + 8
        for name in self.names:
            x = self.x[name]
            svg.line(x, self.top + head_h, x, bottom, color=MUTED, dash=True, arrow=False, sw=1)
            self._head(svg, name, x, self.top)
            self._head(svg, name, x, bottom + 4, small=True)
        open_groups: list[tuple[str, float]] = []
        for item, ry, h in rows:
            kind = item[0]
            if kind == "msg":
                _, a, b, label, reply, color = item
                x1, x2 = self.x[a], self.x[b]
                yy = ry + h - 12
                svg.line(x1, yy, x2 + (-4 if x2 > x1 else 4), yy, color=color, dash=reply,
                         open_head=reply)
                lines = label.count("\n") + 1
                svg.text(min(x1, x2) + 10, yy - 11 - (lines - 1) * 8, label, 13, color=color,
                         anchor="start", halo=True)
            elif kind == "self":
                _, a, label, color = item
                x = self.x[a]
                y1, y2 = ry + 16, ry + h - 8
                svg.path(f"M{x},{y1} H{x + 34} V{y2} H{x + 4}", color=color)
                svg.text(x + 42, (y1 + y2) / 2, label, 13, anchor="start", color=color, halo=True)
            elif kind == "note":
                _, a, b, label, fill, stroke = item
                xa, xb = sorted((self.x[a], self.x[b]))
                svg.rect(xa - 70, ry + 6, xb - xa + 140, h - 12, label, fill=fill, stroke=stroke,
                         size=13, rx=4)
            elif kind == "group":
                open_groups.append((item[1], ry))
            elif kind == "end":
                label, gy = open_groups.pop()
                x0, x1 = 22, self.width - 22
                svg.rect(x0, gy + 4, x1 - x0, ry - gy + 4, fill="none", stroke=MUTED, rx=2,
                         dash=False, sw=1)
                w = 12 + 7.2 * len(label)
                svg.add(f'<path d="M{x0},{gy + 4} h{w} v18 l-8,8 H{x0} z" fill="#eef1f2" '
                        f'stroke="{MUTED}" stroke-width="1"/>')
                svg.text(x0 + 6, gy + 17, label, 12, anchor="start", weight="bold", color=MUTED)
        return svg.render()

    def _head(self, svg: Svg, name: str, x: float, y: float, small: bool = False) -> None:
        kind = self.kinds[name]
        if kind == "actor":
            if small:
                svg.text(x, y + 14, name, 13, weight="bold")
            else:
                svg.actor(x, y, name)
            return
        fill = {"db": KEY_FILL, "sec": ACCENT_FILL, "ext": BLUE_FILL}.get(kind, FILL)
        stroke = {"db": KEY, "sec": ACCENT, "ext": BLUE}.get(kind, LINE)
        w = 150
        hh = 30 if small else 52
        yy = y if small else y + 20
        svg.rect(x - w / 2, yy, w, hh, name, fill=fill, stroke=stroke, size=13, weight="bold")
