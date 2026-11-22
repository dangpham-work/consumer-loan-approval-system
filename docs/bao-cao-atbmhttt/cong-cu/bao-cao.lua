-- Bộ lọc pandoc cho bản .docx của báo cáo: ngắt trang, mục lục tự động, căn giữa hình và chú thích,
-- co ảnh theo khổ A4.

local MAX_W, MAX_H = 16.0, 20.5 -- cm: bề rộng vùng chữ A4 lề 3-2 cm, chiều cao chừa chỗ cho chú thích

local function png_size(path)
  local f = io.open(path, "rb")
  if not f then return nil end
  local data = f:read(24)
  f:close()
  if not data or data:sub(2, 4) ~= "PNG" then return nil end
  local function u32(i)
    local a, b, c, d = data:byte(i, i + 3)
    return ((a * 256 + b) * 256 + c) * 256 + d
  end
  return u32(17), u32(21)
end

function Image(img)
  local w, h = png_size(img.src)
  if w then
    local width = MAX_W
    if width * h / w > MAX_H then width = MAX_H * w / h end
    -- ảnh chụp màn hình rộng 1280 px: không phóng quá khổ thật
    img.attributes.width = string.format("%.2fcm", width)
  end
  return img
end

local TOC = '<w:sdt><w:sdtPr><w:docPartObj><w:docPartGallery w:val="Table of Contents"/><w:docPartUnique/>'
  .. '</w:docPartObj></w:sdtPr><w:sdtContent><w:p><w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r>'
  .. '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText></w:r>'
  .. '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
  .. '<w:r><w:t>Nhấp chuột phải vào đây, chọn Update Field (Cập nhật trường) để hiện mục lục.</w:t></w:r>'
  .. '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:sdtContent></w:sdt>'

function RawBlock(el)
  if el.format == "html" then
    -- Heading 1 đã có pageBreakBefore trong reference.docx nên bỏ ngắt trang thủ công
    if el.text:match("<!%-%- pagebreak %-%->") then return {} end
    if el.text:match("<!%-%- toc %-%->") then return pandoc.RawBlock("openxml", TOC) end
    if el.text:match("^<!%-%-") then return {} end
  end
end

function RawInline(el)
  if el.format == "html" and el.text:match("^<br") then return pandoc.LineBreak() end
end

local function styled(block, style)
  return pandoc.Div({ block }, pandoc.Attr("", {}, { ["custom-style"] = style }))
end

function Para(el)
  if #el.content == 1 and el.content[1].t == "Image" then
    return styled(el, "Hinh")
  end
  if #el.content == 1 and el.content[1].t == "Emph" then
    if pandoc.utils.stringify(el.content[1]):match("^Hình ") then return styled(el, "Chu thich hinh") end
  end
  if el.content[1] and el.content[1].t == "Strong" then
    if pandoc.utils.stringify(el.content[1]):match("^Bảng %d") then return styled(el, "Ten bang") end
  end
end

function Div(el)
  if el.attributes.align == "center" then
    el.attributes.align = nil
    local out = {}
    for _, b in ipairs(el.content) do
      if b.t == "Para" or b.t == "Plain" then table.insert(out, styled(pandoc.Para(b.content), "Bia")) else table.insert(out, b) end
    end
    return out
  end
end
