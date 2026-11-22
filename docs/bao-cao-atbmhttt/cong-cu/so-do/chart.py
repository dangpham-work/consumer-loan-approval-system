"""Biểu đồ thông lượng mã hóa 1 MB, hai chế độ CPU (dạng nhấn mạnh: ChaCha20-Poly1305 màu, còn lại xám)."""
import json, sys
from pathlib import Path

so_lieu = Path(sys.argv[1])
out = Path(sys.argv[2])
modes = [("A. Mặc định: CPU có AES-NI, PCLMULQDQ, AVX-512", "hieu-nang-co-aes-ni.json"),
         ("B. OPENSSL_ia32cap: tắt AES-NI, PCLMULQDQ (OpenSSL bỏ luôn nhánh AVX2/AVX-512)", "hieu-nang-khong-aes-ni.json")]
algos = ["ChaCha20-Poly1305", "AES-256-GCM", "AES-256-CBC + HMAC-SHA256"]
ACCENT, MUTED_BAR = "#2a78d6", "#a8a7a0"
INK, INK2, AXIS, GRID, SURF = "#0b0b0b", "#52514e", "#c3c2b7", "#e1e0d9", "#fcfcfb"
FONT = "Liberation Sans, Arial, sans-serif"
data = [[json.loads((so_lieu / f).read_text())["throughput_mb_s"][a]["1048576"] for a in algos] for _, f in modes]
vmax = 6000 if max(max(r) for r in data) <= 6000 else 10000
W, left, right = 1240, 250, 90
plot_w = W - left - right
bar_h, gap, panel_gap = 26, 14, 40
parts = []
y = 24
def x(v): return left + plot_w * v / vmax
for (title, _), row in zip(modes, data):
    parts.append(f'<text x="{left - 230}" y="{y}" font-family="{FONT}" font-size="15" font-weight="bold" fill="{INK}">{title}</text>')
    top = y + 16
    h = 3 * bar_h + 4 * gap
    for t in range(0, vmax + 1, 1000):
        parts.append(f'<line x1="{x(t)}" y1="{top}" x2="{x(t)}" y2="{top + h}" stroke="{GRID}" stroke-width="1"/>')
    parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + h}" stroke="{AXIS}" stroke-width="1.5"/>')
    for i, (name, v) in enumerate(zip(algos, row)):
        by = top + gap + i * (bar_h + gap)
        color = ACCENT if i == 0 else MUTED_BAR
        w = max(2, x(v) - left)
        parts.append(f'<path d="M{left},{by} h{w - 4} a4,4 0 0 1 4,4 v{bar_h - 8} a4,4 0 0 1 -4,4 h{-(w - 4)} z" fill="{color}"/>')
        parts.append(f'<text x="{left - 12}" y="{by + bar_h / 2}" text-anchor="end" dominant-baseline="middle" font-family="{FONT}" font-size="14" fill="{INK if i == 0 else INK2}" font-weight="{"bold" if i == 0 else "normal"}">{name}</text>')
        parts.append(f'<text x="{x(v) + 8}" y="{by + bar_h / 2}" dominant-baseline="middle" font-family="{FONT}" font-size="14" fill="{INK}">{f"{v:,.0f}".replace(",", ".")}</text>')
    y = top + h + panel_gap
for t in range(0, vmax + 1, 1000):
    parts.append(f'<text x="{x(t)}" y="{y - panel_gap + 18}" text-anchor="middle" font-family="{FONT}" font-size="12" fill="{INK2}">{f"{t:,}".replace(",", ".")}</text>')
parts.append(f'<text x="{left + plot_w / 2}" y="{y - panel_gap + 42}" text-anchor="middle" font-family="{FONT}" font-size="13" fill="{INK2}">Thông lượng mã hóa + tính tag cho dữ liệu 1 MB (MB/s, cao hơn là nhanh hơn)</text>')
H = y - panel_gap + 60
svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"><rect width="100%" height="100%" fill="{SURF}"/>{"".join(parts)}</svg>'
out.write_text(svg, encoding="utf-8")
print("wrote", out, [[round(v) for v in r] for r in data])
