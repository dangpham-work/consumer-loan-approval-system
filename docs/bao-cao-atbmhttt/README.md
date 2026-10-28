# Báo cáo ATBMHTTT: ChaCha20-Poly1305 trong hệ thống xét duyệt vay

Báo cáo học phần An toàn và bảo mật hệ thống thông tin, đề tài *Ứng dụng thuật toán mã hóa xác thực ChaCha20-Poly1305 bảo vệ dữ liệu cá nhân trong hệ thống quản lý và xét duyệt vay tín dụng tiêu dùng*. Bố cục bám theo mục lục của học phần (Chương 1–4, tài liệu tham khảo, phụ lục).

| Tệp | Nội dung |
|---|---|
| [`bao-cao.md`](bao-cao.md) | Bản gốc của báo cáo (đọc trực tiếp trên GitHub) |
| `bao-cao.docx` | Bản Word để nộp và chỉnh sửa |
| `bao-cao.pdf` | Bản PDF 68 trang, mục lục đã có số trang |
| `hinh/` | Sơ đồ (PNG, bản SVG sửa được trong `hinh/svg/`) và ảnh chụp giao diện |
| `so-lieu/` | Số liệu đo hiệu năng gốc (JSON) |
| `scripts/chacha20_minh_hoa.py` | ChaCha20, Poly1305, AEAD cài bằng Python thuần, kiểm chứng với RFC 8439 |
| `scripts/do_hieu_nang.py` | Đo hiệu năng ChaCha20-Poly1305, AES-256-GCM, AES-CBC + HMAC và các cơ chế hỗ trợ |
| `cong-cu/` | Công cụ xuất bản Word/PDF và vẽ sơ đồ |

## Trước khi nộp

1. Mở `bao-cao.docx`, điền tên giảng viên, thành viên nhóm, MSSV, lớp ở trang bìa.
2. Nhấp chuột phải vào mục lục, chọn **Update Field → Update entire table** để Word đánh lại số trang (Word cũng có thể tự hỏi khi mở tệp).

## Chạy lại các thử nghiệm

```bash
uv run python docs/bao-cao-atbmhttt/scripts/chacha20_minh_hoa.py
```

```bash
uv run python docs/bao-cao-atbmhttt/scripts/do_hieu_nang.py --json docs/bao-cao-atbmhttt/so-lieu/hieu-nang-co-aes-ni.json
```

```bash
OPENSSL_ia32cap="~0x200000200000000" uv run python docs/bao-cao-atbmhttt/scripts/do_hieu_nang.py --json docs/bao-cao-atbmhttt/so-lieu/hieu-nang-khong-aes-ni.json
```

Số liệu phụ thuộc máy chạy; báo cáo dùng số liệu đo trên máy ảo Intel Xeon 2,1 GHz, 4 nhân.

## Xuất lại Word và PDF sau khi sửa `bao-cao.md`

Cần pandoc 3.x; muốn có PDF thì cần thêm LibreOffice và gói `python3-uno`.

```bash
docs/bao-cao-atbmhttt/cong-cu/xuat-ban.sh
```

Sơ đồ được sinh từ `cong-cu/so-do/diagrams.py` (SVG) rồi chuyển sang PNG bằng Playwright (`render.js`); biểu đồ hiệu năng sinh từ `cong-cu/so-do/chart.py` theo số liệu trong `so-lieu/`.
