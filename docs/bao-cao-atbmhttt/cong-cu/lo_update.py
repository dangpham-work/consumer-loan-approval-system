"""Mở .docx bằng LibreOffice (UNO), cập nhật mục lục và các trường, xuất PDF.

Chạy: python3 lo_update.py <vào.docx> <ra.pdf> [ra.docx]  (cần LibreOffice và gói python3-uno)
"""
import subprocess
import sys
import time
from pathlib import Path

import uno
from com.sun.star.beans import PropertyValue


def prop(name, value):
    p = PropertyValue()
    p.Name, p.Value = name, value
    return p


src, pdf = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
docx_out = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else None
proc = subprocess.Popen(["soffice", "--headless", "--invisible", "--nologo", "--norestore",
                         "--accept=socket,host=127.0.0.1,port=2002;urp;"])
try:
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
    for _ in range(60):
        try:
            ctx = resolver.resolve("uno:socket,host=127.0.0.1,port=2002;urp;StarOffice.ComponentContext")
            break
        except Exception:
            time.sleep(1)
    desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
    doc = desktop.loadComponentFromURL(src.as_uri(), "_blank", 0, (prop("Hidden", True),))
    indexes = doc.getDocumentIndexes()
    for i in range(indexes.getCount()):
        indexes.getByIndex(i).update()
    doc.getTextFields().refresh()
    for i in range(indexes.getCount()):  # lần hai: số trang sau khi mục lục đã chiếm chỗ
        indexes.getByIndex(i).update()
    doc.storeToURL(pdf.as_uri(), (prop("FilterName", "writer_pdf_Export"),))
    if docx_out:
        doc.storeToURL(docx_out.as_uri(), (prop("FilterName", "MS Word 2007 XML"),))
    count = indexes.getCount()
    doc.close(True)
    print("indexes:", count, "->", pdf)
finally:
    try:
        desktop.terminate()
    except Exception:
        pass
    proc.wait(timeout=30)
