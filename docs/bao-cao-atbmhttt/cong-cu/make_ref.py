"""Tạo reference.docx cho pandoc: Times New Roman 13, A4, lề 3-2-2-2 cm, bảng kẻ khung, số trang.

Chạy: pandoc -o mac-dinh.docx --print-default-data-file reference.docx
      python3 make_ref.py mac-dinh.docx reference.docx
"""
import re
import sys
import tempfile
import zipfile
from pathlib import Path

src, out = Path(sys.argv[1]), Path(sys.argv[2])
work = Path(tempfile.mkdtemp())
with zipfile.ZipFile(src) as z:
    z.extractall(work)
styles = (work / "word/styles.xml").read_text(encoding="utf-8")

FONT = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="Times New Roman" w:cs="Times New Roman" />'
styles = re.sub(
    r"<w:docDefaults>.*?</w:docDefaults>",
    f"""<w:docDefaults><w:rPrDefault><w:rPr>{FONT}<w:sz w:val="26" /><w:szCs w:val="26" />
<w:lang w:val="vi-VN" w:eastAsia="en-US" w:bidi="ar-SA" /></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="312" w:lineRule="auto" /></w:pPr></w:pPrDefault></w:docDefaults>""",
    styles, flags=re.S,
)


def para_style(sid: str, name: str, ppr: str, rpr: str = "", based: str = "Normal") -> str:
    return (f'<w:style w:type="paragraph" w:customStyle="1" w:styleId="{sid}"><w:name w:val="{name}" />'
            f'<w:basedOn w:val="{based}" /><w:qFormat /><w:pPr>{ppr}</w:pPr><w:rPr>{rpr}</w:rPr></w:style>')


def replace_style(sid: str, xml: str) -> None:
    global styles
    pattern = r'<w:style [^>]*w:styleId="%s".*?</w:style>' % sid
    if re.search(pattern, styles, flags=re.S):
        styles = re.sub(pattern, lambda _: xml, styles, count=1, flags=re.S)
    else:
        styles = styles.replace("</w:styles>", xml + "</w:styles>")


def heading(level: int, size: int, extra_ppr: str, extra_rpr: str) -> str:
    return (f'<w:style w:type="paragraph" w:styleId="Heading{level}"><w:name w:val="heading {level}" />'
            f'<w:basedOn w:val="Normal" /><w:next w:val="BodyText" /><w:uiPriority w:val="9" /><w:qFormat />'
            f'<w:pPr><w:keepNext /><w:keepLines />{extra_ppr}<w:outlineLvl w:val="{level - 1}" /></w:pPr>'
            f'<w:rPr>{FONT}<w:b /><w:bCs />{extra_rpr}<w:color w:val="000000" />'
            f'<w:sz w:val="{size}" /><w:szCs w:val="{size}" /></w:rPr></w:style>')


replace_style("Heading1", heading(1, 28, '<w:pageBreakBefore /><w:spacing w:before="0" w:after="240" /><w:jc w:val="center" />', ""))
replace_style("Heading2", heading(2, 26, '<w:spacing w:before="240" w:after="120" />', ""))
replace_style("Heading3", heading(3, 26, '<w:spacing w:before="180" w:after="80" />', "<w:i /><w:iCs />"))
body = '<w:spacing w:before="0" w:after="120" w:line="360" w:lineRule="auto" /><w:jc w:val="both" />'
replace_style("BodyText", '<w:style w:type="paragraph" w:styleId="BodyText"><w:name w:val="Body Text" />'
              f'<w:basedOn w:val="Normal" /><w:link w:val="BodyTextChar" /><w:qFormat /><w:pPr>{body}</w:pPr></w:style>')
replace_style("FirstParagraph", '<w:style w:type="paragraph" w:styleId="FirstParagraph"><w:name w:val="First Paragraph" />'
              f'<w:basedOn w:val="BodyText" /><w:next w:val="BodyText" /><w:qFormat /><w:pPr>{body}</w:pPr></w:style>')
replace_style("Compact", '<w:style w:type="paragraph" w:styleId="Compact"><w:name w:val="Compact" />'
              '<w:basedOn w:val="BodyText" /><w:qFormat /><w:pPr><w:spacing w:before="0" w:after="60" w:line="312" w:lineRule="auto" /></w:pPr></w:style>')
border = '<w:{0} w:val="single" w:sz="4" w:space="0" w:color="808080" />'
borders = "".join(border.format(b) for b in ("top", "left", "bottom", "right", "insideH", "insideV"))
replace_style("Table", '<w:style w:type="table" w:default="1" w:styleId="Table"><w:name w:val="Table" />'
              '<w:basedOn w:val="TableNormal" /><w:qFormat /><w:pPr><w:spacing w:before="40" w:after="40" w:line="264" w:lineRule="auto" /><w:jc w:val="left" /></w:pPr>'
              '<w:rPr><w:sz w:val="22" /><w:szCs w:val="22" /></w:rPr>'
              f'<w:tblPr><w:tblInd w:w="0" w:type="dxa" /><w:tblBorders>{borders}</w:tblBorders>'
              '<w:tblCellMar><w:top w:w="40" w:type="dxa" /><w:left w:w="80" w:type="dxa" /><w:bottom w:w="40" w:type="dxa" />'
              '<w:right w:w="80" w:type="dxa" /></w:tblCellMar></w:tblPr>'
              '<w:tblStylePr w:type="firstRow"><w:rPr><w:b /><w:bCs /></w:rPr>'
              '<w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="E7EEF0" /></w:tcPr></w:tblStylePr></w:style>')
replace_style("SourceCode", '<w:style w:type="paragraph" w:customStyle="1" w:styleId="SourceCode"><w:name w:val="Source Code" />'
              '<w:basedOn w:val="Normal" /><w:link w:val="VerbatimChar" /><w:pPr><w:wordWrap w:val="off" />'
              '<w:shd w:val="clear" w:color="auto" w:fill="F4F6F6" /><w:spacing w:before="60" w:after="60" w:line="240" w:lineRule="auto" /></w:pPr>'
              '<w:rPr><w:sz w:val="18" /><w:szCs w:val="18" /></w:rPr></w:style>')
replace_style("VerbatimChar", '<w:style w:type="character" w:customStyle="1" w:styleId="VerbatimChar"><w:name w:val="Verbatim Char" />'
              '<w:basedOn w:val="BodyTextChar" /><w:rPr><w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" w:cs="Courier New" />'
              '<w:sz w:val="20" /></w:rPr></w:style>')
center = '<w:jc w:val="center" />'
styles = styles.replace("</w:styles>", "".join([
    para_style("Bia", "Bia", f'{center}<w:spacing w:before="0" w:after="200" w:line="360" w:lineRule="auto" />',
               '<w:sz w:val="28" /><w:szCs w:val="28" />'),
    para_style("Hinh", "Hinh", f'{center}<w:keepNext /><w:spacing w:before="120" w:after="0" />'),
    para_style("Chuthichhinh", "Chu thich hinh", f'{center}<w:spacing w:before="60" w:after="240" />',
               '<w:sz w:val="24" /><w:szCs w:val="24" />'),
    para_style("Tenbang", "Ten bang", f'{center}<w:keepNext /><w:spacing w:before="200" w:after="80" />',
               '<w:sz w:val="24" /><w:szCs w:val="24" />'),
]) + "</w:styles>")
(work / "word/styles.xml").write_text(styles, encoding="utf-8")

footer = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:pPr><w:jc w:val="center" /></w:pPr>
<w:r><w:fldChar w:fldCharType="begin" /></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>
<w:r><w:fldChar w:fldCharType="separate" /></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end" /></w:r></w:p></w:ftr>"""
(work / "word/footer1.xml").write_text(footer, encoding="utf-8")
rels = (work / "word/_rels/document.xml.rels").read_text(encoding="utf-8")
if "footer1.xml" not in rels:
    rels = rels.replace("</Relationships>",
                        '<Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" '
                        'Id="rIdFooter1" Target="footer1.xml" /></Relationships>')
    (work / "word/_rels/document.xml.rels").write_text(rels, encoding="utf-8")
ct = (work / "[Content_Types].xml").read_text(encoding="utf-8")
if "footer1.xml" not in ct:
    ct = ct.replace("</Types>", '<Override PartName="/word/footer1.xml" '
                    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml" /></Types>')
    (work / "[Content_Types].xml").write_text(ct, encoding="utf-8")
doc = (work / "word/document.xml").read_text(encoding="utf-8")
doc = doc.replace("<w:sectPr />",
                  '<w:sectPr><w:footerReference w:type="default" r:id="rIdFooter1" /><w:pgSz w:w="11906" w:h="16838" />'
                  '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1701" w:header="567" w:footer="567" w:gutter="0" />'
                  '</w:sectPr>')
(work / "word/document.xml").write_text(doc, encoding="utf-8")

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(work.rglob("*")):
        if f.is_file():
            z.write(f, f.relative_to(work).as_posix())
print("wrote", out)
