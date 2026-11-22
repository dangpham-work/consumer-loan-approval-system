#!/usr/bin/env bash
# Xuat bao-cao.docx tu bao-cao.md, va bao-cao.pdf (muc luc da cap nhat) neu co LibreOffice.
set -euo pipefail
cd "$(dirname "$0")/.."
pandoc bao-cao.md -f markdown-implicit_figures-tex_math_dollars -t docx --columns=40 \
  --reference-doc cong-cu/reference.docx --lua-filter cong-cu/bao-cao.lua --resource-path=. \
  -o bao-cao.docx
echo "wrote bao-cao.docx"
if command -v soffice >/dev/null && python3 -c "import uno" 2>/dev/null; then
  python3 cong-cu/lo_update.py bao-cao.docx bao-cao.pdf
fi
