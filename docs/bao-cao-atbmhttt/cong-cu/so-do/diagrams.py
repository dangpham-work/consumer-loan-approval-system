"""Sinh các sơ đồ SVG của báo cáo. Chạy: python3 diagrams.py <thư mục ra>."""

import sys
from pathlib import Path

from svg import (ACCENT, ACCENT_FILL, BLUE, BLUE_FILL, FILL, INK, KEY, KEY_FILL, LINE, MUTED,
                 WARN, WARN_FILL, Sequence, Svg)


def zone(s: Svg, x: float, y: float, w: float, h: float, label: str) -> None:
    s.rect(x, y, w, h, fill="#fbfcfc", stroke=MUTED, dash=True, rx=10, sw=1.2)
    s.text(x + 12, y + 18, label, 13, anchor="start", color=MUTED, weight="bold")


# --- 3.3.1 Kiến trúc tổng thể ------------------------------------------------------------------------

def kien_truc() -> str:
    s = Svg(1240, 700)
    zone(s, 16, 40, 210, 360, "Internet")
    zone(s, 246, 40, 190, 360, "DMZ")
    zone(s, 456, 40, 470, 640, "Vùng ứng dụng (Docker network app)")
    zone(s, 946, 40, 278, 640, "Vùng dữ liệu (network data, internal)")
    s.rect(36, 90, 170, 80, "Trình duyệt\nkhách hàng", fill=BLUE_FILL, stroke=BLUE, weight="bold")
    s.rect(36, 210, 170, 80, "Trình duyệt\nnhân viên", fill=BLUE_FILL, stroke=BLUE, weight="bold")
    s.rect(36, 310, 170, 70, "Ứng dụng xác thực\n(TOTP, điện thoại)", fill=BLUE_FILL,
           stroke=BLUE, size=13)
    s.rect(262, 150, 158, 120, "Reverse proxy\nNginx\nTLS 1.3 (:443)\n(dự kiến)", fill=FILL,
           dash=True, size=13)
    s.line(206, 130, 262, 190)
    s.line(206, 250, 262, 230)
    s.text(234, 214, "HTTPS", 11, color=MUTED, halo=True)
    s.line(121, 310, 121, 290, arrow=False, dash=True, color=MUTED)
    # Máy chủ ứng dụng
    s.rect(476, 70, 430, 590, fill="#ffffff", stroke=LINE, rx=8)
    s.text(691, 92, "Máy chủ ứng dụng: Uvicorn + FastAPI (Python 3.12)", 14, weight="bold")
    layers = [
        ("Tầng trình bày: Jinja2 /app, REST API\nCSRF, cookie HttpOnly/Secure/SameSite,\ngiới hạn tần suất", 112),
        ("Tầng nghiệp vụ (services): RBAC,\nphân tách nhiệm vụ, IntegrityService,\nAuditService (cùng giao dịch)", 192),
        ("Tầng miền (domain): máy trạng thái\nhồ sơ vay, chuỗi băm nhật ký,\nquy tắc nghiệp vụ", 272),
        ("Tầng truy cập dữ liệu: SQLAlchemy,\ntruy vấn tham số hóa", 352),
    ]
    for label, y in layers:
        s.rect(492, y, 260, 64, label, size=11)
    for y in (176, 256, 336):
        s.line(622, y, 622, y + 16)
    s.rect(768, 112, 124, 304, fill=ACCENT_FILL, stroke=ACCENT)
    s.text(830, 130, "security/", 13, weight="bold", color=ACCENT)
    items = ["ChaCha20-\nPoly1305", "HKDF-\nSHA256", "HMAC-\nSHA256", "Argon2id", "TOTP\nRFC 6238",
             "Giới hạn\ntần suất"]
    for i, it in enumerate(items):
        s.rect(780, 146 + i * 44, 100, 38, it, fill="#ffffff", stroke=ACCENT, size=11)
    s.line(752, 260, 768, 260, color=ACCENT)
    s.rect(492, 440, 400, 70,
           "Bộ lập lịch 00:30: tác vụ hằng đêm (quá hạn, nhắc nợ, chấm lại)", size=12)
    s.rect(492, 530, 400, 110, fill=BLUE_FILL, stroke=BLUE)
    s.text(692, 548, "Dịch vụ ngoài (giả lập)", 13, weight="bold", color=BLUE)
    for i, it in enumerate(["SMS (OTP)", "Email", "CIC", "Cổng\nthanh toán"]):
        s.rect(504 + i * 96, 572, 88, 50, it, fill="#ffffff", stroke=BLUE, size=12)
    s.line(420, 210, 476, 210)
    s.text(448, 196, ":8000", 12, color=MUTED)
    # Dữ liệu
    s.rect(966, 70, 238, 250, fill=KEY_FILL, stroke=KEY)
    s.text(1085, 92, "MySQL 8.4 (:3306)", 14, weight="bold", color=KEY)
    rows = ["customers: CCCD, thu nhập\n= bản mã ChaCha20-Poly1305", "national_id_hash\n= HMAC-SHA256 (blind index)",
            "audit_logs, approval_decisions:\nchỉ SELECT, INSERT", "trigger BR07: khóa hồ sơ\nđã phê duyệt"]
    for i, r in enumerate(rows):
        s.rect(978, 108 + i * 52, 214, 46, r, fill="#ffffff", stroke=KEY, size=11)
    s.rect(966, 340, 238, 70, "Lưu trữ giấy tờ\nvar/documents (ngoài thư mục web)", size=12)
    s.rect(966, 430, 238, 230, fill=WARN_FILL, stroke=WARN)
    s.text(1085, 452, "Bí mật (biến môi trường)", 13, weight="bold", color=WARN)
    for i, k in enumerate(["DATA_ENC_KEY", "HMAC_INTEGRITY_KEY", "BLIND_INDEX_KEY", "SESSION_SECRET"]):
        s.rect(986, 472 + i * 44, 198, 36, k, fill="#ffffff", stroke=WARN, size=12, mono=True)
    s.line(906, 230, 966, 200)
    s.text(936, 246, "loan_app", 11, color=MUTED, halo=True)
    s.line(906, 360, 966, 375)
    s.line(966, 600, 906, 600, dash=True, color=WARN)
    s.text(936, 575, "nạp khi\nkhởi động", 10, color=WARN, halo=True)
    return s.render()


# --- 3.3.3 Use case ----------------------------------------------------------------------------------

def use_case() -> str:
    s = Svg(1240, 800)
    s.rect(270, 20, 700, 770, fill="#ffffff", stroke=LINE, rx=4)
    s.text(620, 42, "Hệ thống quản lý và xét duyệt vay tín dụng tiêu dùng", 15, weight="bold")
    uc = {
        "dk": (440, 110, "Đăng ký tài khoản\n(OTP qua SMS)"),
        "nop": (440, 230, "Nộp hồ sơ vay\n(mã hóa ChaCha20-Poly1305)"),
        "tra": (440, 350, "Tra cứu khách hàng\ntheo CCCD (blind index)"),
        "pii": (440, 470, "Xem CCCD, thu nhập\nđầy đủ (ghi VIEW_PII)"),
        "pd": (800, 110, "Phê duyệt hồ sơ vay\n(ký HMAC snapshot)"),
        "gn": (800, 230, "Giải ngân (kiểm tra toàn\nvẹn + xác thực lại TOTP)"),
        "nk": (800, 350, "Kiểm tra toàn vẹn\nchuỗi nhật ký"),
        "qt": (800, 470, "Quản lý tài khoản, vai trò\n(xác thực lại TOTP)"),
        "login": (620, 600, "Đăng nhập\n(mật khẩu Argon2id)"),
        "totp": (820, 720, "Xác thực TOTP\n(RFC 6238)"),
        "enroll": (420, 720, "Đăng ký khóa TOTP\nlần đầu"),
    }
    actors = {
        "Khách hàng": (110, 80), "NV tín dụng": (110, 290), "Thẩm định viên": (110, 440),
        "Người dùng (mọi tác nhân)": (110, 580),
        "Quản lý phê duyệt": (1130, 80), "NV giải ngân": (1130, 200),
        "Kiểm soát viên": (1130, 320), "Quản trị viên": (1130, 440),
    }
    links = {
        "Khách hàng": ["dk", "nop"], "NV tín dụng": ["tra", "nop"],
        "Thẩm định viên": ["pii"], "Người dùng (mọi tác nhân)": ["login"],
        "Quản lý phê duyệt": ["pd"], "NV giải ngân": ["gn"], "Kiểm soát viên": ["nk"],
        "Quản trị viên": ["qt"],
    }
    for name, targets in links.items():
        ax, ay = actors[name]
        for t in targets:
            cx, cy, _ = uc[t]
            side = 1 if cx > ax else -1
            s.line(ax + side * 20, ay + 30, cx - side * 125, cy, arrow=False, color=MUTED, sw=1.1)
    for name, (x, y) in actors.items():
        s.actor(x, y, name)
    for key, (cx, cy, label) in uc.items():
        sec = key in ("login", "totp", "enroll")
        s.ellipse(cx, cy, 125, 40, label, fill=ACCENT_FILL if sec else FILL,
                  stroke=ACCENT if sec else LINE, size=12)

    def dep(a: str, b: str, label: str) -> None:
        x1, y1, _ = uc[a]
        x2, y2, _ = uc[b]
        dx, dy = x2 - x1, y2 - y1
        d = (dx * dx + dy * dy) ** 0.5
        sx, sy = x1 + dx / d * 90, y1 + dy / d * 38
        ex, ey = x2 - dx / d * 95, y2 - dy / d * 40
        s.line(sx, sy, ex, ey, dash=True, open_head=True, color=ACCENT)
        s.text((sx + ex) / 2 + 10, (sy + ey) / 2 - 10, label, 11, color=ACCENT, anchor="start",
               halo=True)

    dep("login", "totp", "«include» (nhân viên)")
    dep("enroll", "login", "«extend»")
    return s.render()


# --- 3.3.4 Tuần tự --------------------------------------------------------------------------------

def seq_dang_nhap() -> str:
    q = Sequence([("Nhân viên", "actor"), ("Web / API", "app"), ("AuthService", "sec"),
                  ("FieldCipher", "sec"), ("MySQL", "db")], width=1240)
    q.msg("Nhân viên", "Web / API", "1. POST /app/login (tên đăng nhập, mật khẩu)")
    q.self_msg("Web / API", "2. Giới hạn 10 lượt/phút/IP (SR12), kiểm tra CSRF")
    q.msg("Web / API", "AuthService", "3. login(username, password)")
    q.msg("AuthService", "MySQL", "4. SELECT users WHERE username = ?")
    q.self_msg("AuthService", "5. Argon2id verify (chạy cả khi tài khoản không tồn tại)")
    q.group("alt  sai mật khẩu")
    q.msg("AuthService", "MySQL", "6a. failed_attempts + 1; đủ 5 lần → locked_until = now + 15 phút;\nghi LOGIN_FAIL")
    q.msg("Web / API", "Nhân viên", "6b. \"Sai tên đăng nhập hoặc mật khẩu\" (thông báo chung)", reply=True)
    q.end_group()
    q.msg("AuthService", "MySQL", "7. INSERT sessions(token_hash = HMAC-SHA256(SESSION_SECRET, token), stage = MFA)")
    q.msg("Web / API", "Nhân viên", "8. Set-Cookie: session (HttpOnly, Secure, SameSite=Strict) → /app/login/otp", reply=True)
    q.msg("Nhân viên", "Web / API", "9. POST /app/login/otp (mã 6 số từ ứng dụng xác thực)")
    q.msg("Web / API", "AuthService", "10. verify_login_otp(token, code)")
    q.msg("AuthService", "FieldCipher", "11. decrypt(totp_secret_enc, \"users.totp_secret:{id}\")")
    q.self_msg("FieldCipher", "12. Kiểm tra tag Poly1305\nrồi giải mã ChaCha20")
    q.msg("FieldCipher", "AuthService", "13. khóa TOTP K (160 bit)", reply=True)
    q.self_msg("AuthService", "14. HMAC-SHA1(K, ⌊t/30⌋), lệch ±1 bước,\nbước > totp_last_step (chống phát lại)")
    q.msg("AuthService", "MySQL", "15. UPDATE totp_last_step, sessions.stage = FULL; ghi LOGIN_SUCCESS (chuỗi băm)")
    q.msg("Web / API", "Nhân viên", "16. Chuyển tới trang chủ theo vai trò", reply=True)
    return q.render()


def seq_dang_ky_totp() -> str:
    q = Sequence([("Nhân viên", "actor"), ("Ứng dụng xác thực", "ext"), ("Web / API", "app"),
                  ("AuthService", "sec"), ("FieldCipher", "sec"), ("MySQL", "db")], width=1240)
    q.msg("Nhân viên", "Web / API", "1. Đăng nhập lần đầu bằng mật khẩu tạm (phiên SETUP)")
    q.msg("Nhân viên", "Web / API", "2. Đổi mật khẩu tạm (≥ 10 ký tự) → Argon2id, hủy các phiên khác")
    q.msg("Web / API", "AuthService", "3. start_totp_enrollment()")
    q.self_msg("AuthService", "4. K = 20 byte ngẫu nhiên (CSPRNG)")
    q.msg("AuthService", "FieldCipher", "5. encrypt(base32(K), \"users.totp_secret:{id}\")")
    q.msg("FieldCipher", "AuthService", "6. 02 ‖ nonce ‖ ciphertext ‖ tag", reply=True)
    q.msg("AuthService", "MySQL", "7. UPDATE users.totp_secret_enc; ghi TOTP_ENROLL_START")
    q.msg("Web / API", "Nhân viên", "8. Mã QR: otpauth://totp/LoanSystem:{user}?secret=K", reply=True)
    q.note("Nhân viên", "Ứng dụng xác thực", "Kênh ngoài băng: K chỉ đi qua màn hình một lần,\nkhông lưu dạng rõ ở máy chủ")
    q.msg("Nhân viên", "Ứng dụng xác thực", "9. Quét mã QR")
    q.msg("Ứng dụng xác thực", "Nhân viên", "10. Mã 6 số của bước thời gian hiện tại", reply=True)
    q.msg("Nhân viên", "Web / API", "11. POST mã xác nhận")
    q.msg("Web / API", "AuthService", "12. confirm_totp_enrollment(code)")
    q.msg("AuthService", "MySQL", "13. status = ACTIVE, phiên FULL; ghi TOTP_ENROLL")
    return q.render()


def seq_ma_hoa_truong() -> str:
    q = Sequence([("Khách hàng", "actor"), ("Web / API", "app"), ("ApplicationService", "app"),
                  ("FieldCipher", "sec"), ("MySQL", "db"), ("Thẩm định viên", "actor")],
                 width=1240)
    q.group("Ghi: khách hàng khai thông tin tài chính (bước 2)")
    q.msg("Khách hàng", "Web / API", "1. POST CCCD, thu nhập, số tài khoản nhận")
    q.self_msg("Web / API", "2. CSRF, schema, chỉ nhận trường cho phép")
    q.msg("Web / API", "ApplicationService", "3. update_finance()")
    q.self_msg("ApplicationService", "4. blind index =\nHMAC-SHA256(BLIND_INDEX_KEY, CCCD)")
    q.msg("ApplicationService", "FieldCipher", "5. encrypt(CCCD, \"customers.national_id:{id}\")")
    q.self_msg("FieldCipher", "6. nonce 96 bit ngẫu nhiên; AAD = 02 ‖ ngữ cảnh;\nChaCha20 ⊕ bản rõ, Poly1305 → tag")
    q.msg("FieldCipher", "ApplicationService", "7. 02 ‖ nonce ‖ ciphertext ‖ tag", reply=True)
    q.msg("ApplicationService", "MySQL", "8. UPDATE customers (national_id_enc, national_id_hash);\nAuditService.log trong cùng giao dịch")
    q.end_group()
    q.group("Đọc: thẩm định viên bấm «Hiện» trên M06")
    q.msg("Thẩm định viên", "Web / API", "9. Hiện CCCD (quyền CUSTOMER_VIEW_PII)")
    q.msg("Web / API", "ApplicationService", "10. kiểm tra quyền, phân tách nhiệm vụ")
    q.msg("ApplicationService", "MySQL", "11. SELECT national_id_enc")
    q.msg("ApplicationService", "FieldCipher", "12. decrypt(blob, \"customers.national_id:{id}\")")
    q.self_msg("FieldCipher", "13. tính lại tag, so sánh thời gian hằng;\nkhớp mới giải mã")
    q.msg("ApplicationService", "MySQL", "14. ghi VIEW_PII (quá 20 lượt/giờ → cảnh báo CRITICAL)")
    q.msg("Web / API", "Thẩm định viên", "15. CCCD đầy đủ (Cache-Control: no-store)", reply=True)
    q.end_group()
    return q.render()


def seq_giai_ngan() -> str:
    q = Sequence([("Quản lý phê duyệt", "actor"), ("NV giải ngân", "actor"), ("Web / API", "app"),
                  ("IntegrityService", "sec"), ("FieldCipher", "sec"), ("MySQL", "db"),
                  ("Cổng thanh toán", "ext")], width=1240)
    q.msg("Quản lý phê duyệt", "Web / API", "1. POST phê duyệt (kèm version)")
    q.self_msg("Web / API", "2. RBAC, SoD (SUC01), khóa lạc quan")
    q.msg("Web / API", "IntegrityService", "3. sign(hồ sơ vay)")
    q.msg("IntegrityService", "FieldCipher", "4. decrypt(receiving_account_enc)")
    q.self_msg("IntegrityService", "5. snapshot chuẩn hóa →\nHMAC-SHA256(HMAC_INTEGRITY_KEY)")
    q.msg("IntegrityService", "MySQL", "6. INSERT approval_decisions (snapshot_hash, key_version)")
    q.msg("NV giải ngân", "Web / API", "7. Mở M08 / POST giải ngân + mã TOTP")
    q.msg("Web / API", "IntegrityService", "8. verify (SUC02)")
    q.msg("IntegrityService", "FieldCipher", "9. decrypt tài khoản nhận (xác thực Poly1305)")
    q.self_msg("IntegrityService", "10. dựng lại snapshot, so sánh HMAC\nthời gian hằng")
    q.group("alt  không khớp (cột bị sửa, bản mã bị sửa hoặc chép từ hồ sơ khác)")
    q.msg("IntegrityService", "MySQL", "11a. APPROVED → LOCKED; INTEGRITY_FAIL (CRITICAL); báo Kiểm soát viên")
    q.msg("Web / API", "NV giải ngân", "12a. 409 \"Hồ sơ vay đã bị khóa\"", reply=True, color=WARN)
    q.end_group()
    q.group("khớp")
    q.self_msg("Web / API", "11b. xác thực lại TOTP (step-up)")
    q.msg("Web / API", "Cổng thanh toán", "12b. chuyển tiền (idempotency key)")
    q.msg("Web / API", "MySQL", "13b. DISBURSED, sinh lịch trả nợ, ghi DISBURSE")
    q.end_group()
    return q.render()


# --- 2.2 Thuật toán ----------------------------------------------------------------------------------

def chacha_state() -> str:
    s = Svg(1240, 560)
    s.text(300, 26, "Ma trận trạng thái 4×4 từ 32 bit (512 bit)", 15, weight="bold")
    cells = [
        ("hằng số", ["\"expa\"\n61707865", "\"nd 3\"\n3320646e", "\"2-by\"\n79622d32", "\"te k\"\n6b206574"]),
        ("khóa", ["k0", "k1", "k2", "k3"]),
        ("khóa", ["k4", "k5", "k6", "k7"]),
        ("đếm/nonce", ["bộ đếm\n32 bit", "nonce n0", "nonce n1", "nonce n2"]),
    ]
    fills = {"hằng số": (FILL, LINE), "khóa": (KEY_FILL, KEY), "đếm/nonce": (BLUE_FILL, BLUE)}
    for r, (kind, row) in enumerate(cells):
        f, st = fills[kind]
        for c, label in enumerate(row):
            s.rect(60 + c * 120, 50 + r * 80, 112, 72, label, fill=f, stroke=st, size=13,
                   mono=r == 0)
            s.text(60 + c * 120 + 10, 50 + r * 80 + 12, str(r * 4 + c), 10, anchor="start",
                   color=MUTED)
    s.text(300, 385, "Khóa 256 bit = 8 từ k0..k7 (little-endian); nonce 96 bit; bộ đếm khối 32 bit", 12,
           color=MUTED)
    # vòng cột và vòng chéo
    s.text(300, 418, "Một vòng kép = 4 quarter-round theo cột + 4 theo đường chéo; 10 vòng kép = 20 vòng", 13,
           weight="bold")
    def mini(x0: float, title: str, groups: list[list[int]]) -> None:
        colors = ["#0f6e5a", "#1d4f91", "#8a5a00", "#b42318"]
        s.text(x0 + 88, 446, title, 12, weight="bold")
        for idx in range(16):
            r, c = divmod(idx, 4)
            g = next(i for i, grp in enumerate(groups) if idx in grp)
            s.rect(x0 + c * 44, 460 + r * 22, 40, 20, str(idx), fill="#ffffff", stroke=colors[g],
                   size=11, rx=3, color=colors[g], sw=2)
    mini(80, "QR theo cột", [[0, 4, 8, 12], [1, 5, 9, 13], [2, 6, 10, 14], [3, 7, 11, 15]])
    mini(330, "QR theo đường chéo", [[0, 5, 10, 15], [1, 6, 11, 12], [2, 7, 8, 13], [3, 4, 9, 14]])
    # quarter round: 4 dây
    x0 = 700
    s.text(x0 + 250, 26, "Quarter-round QR(a, b, c, d): chỉ cộng mod 2³², XOR, xoay bit (ARX)", 15,
           weight="bold")
    wires = {"a": x0 + 60, "b": x0 + 180, "c": x0 + 300, "d": x0 + 420}
    for name, x in wires.items():
        s.text(x, 56, name, 15, weight="bold", mono=True)
        s.line(x, 68, x, 520, arrow=True, color=LINE, sw=1.4)
        s.text(x, 540, name + "'", 15, weight="bold", mono=True)
    ops = [("a", "b", "+"), ("d", "a", "⊕"), ("d", None, "<<<16"), ("c", "d", "+"), ("b", "c", "⊕"),
           ("b", None, "<<<12"), ("a", "b", "+"), ("d", "a", "⊕"), ("d", None, "<<<8"),
           ("c", "d", "+"), ("b", "c", "⊕"), ("b", None, "<<<7")]
    for i, (dst, src, op) in enumerate(ops):
        y = 92 + i * 36
        xd = wires[dst]
        if src is None:
            s.rect(xd - 34, y - 12, 68, 24, op, fill=KEY_FILL, stroke=KEY, size=12, rx=4, mono=True)
        else:
            xs = wires[src]
            s.line(xs, y, xd + (14 if xs > xd else -14), y, color=ACCENT, sw=1.2)
            s.add(f'<circle cx="{xd}" cy="{y}" r="13" fill="#ffffff" stroke="{ACCENT}" stroke-width="1.6"/>')
            s.text(xd, y + 1, "+" if op == "+" else "⊕", 16, weight="bold", color=ACCENT)
    return s.render()


def aead_encrypt() -> str:
    s = Svg(1240, 470)
    s.text(620, 22, "Mã hóa ChaCha20-Poly1305 (RFC 8439 mục 2.8)", 16, weight="bold")
    s.rect(30, 60, 170, 56, "Khóa K (256 bit)", fill=KEY_FILL, stroke=KEY, weight="bold")
    s.rect(30, 140, 170, 56, "Nonce N (96 bit)\nngẫu nhiên, duy nhất", fill=BLUE_FILL, stroke=BLUE, size=13)
    s.rect(30, 300, 170, 56, "Bản rõ P", weight="bold")
    s.rect(1050, 60, 170, 70, "AAD (không mã hóa)\n02 ‖ \"bảng.cột:id\"", size=12)
    s.rect(270, 60, 200, 70, "ChaCha20(K, N,\nbộ đếm = 0)", fill=ACCENT_FILL, stroke=ACCENT)
    s.rect(270, 190, 200, 70, "ChaCha20(K, N,\nbộ đếm = 1, 2, …)", fill=ACCENT_FILL, stroke=ACCENT)
    s.line(200, 88, 270, 95)
    s.line(200, 168, 270, 105)
    s.line(200, 98, 270, 215)
    s.line(200, 168, 270, 230)
    s.rect(540, 60, 200, 70, "32 byte đầu = khóa\nPoly1305 dùng một lần\n(r ‖ s)", fill=KEY_FILL,
           stroke=KEY, size=12)
    s.line(470, 95, 540, 95)
    s.text(370, 280, "dòng khóa", 12, color=MUTED)
    s.add(f'<circle cx="370" cy="328" r="18" fill="#fff" stroke="{INK}" stroke-width="1.6"/>')
    s.text(370, 329, "⊕", 22, weight="bold")
    s.line(370, 260, 370, 308)
    s.line(200, 328, 350, 328)
    s.rect(540, 300, 200, 56, "Bản mã C\n(dài bằng P)", weight="bold")
    s.line(388, 328, 540, 328)
    s.rect(800, 180, 230, 130,
           "Poly1305(r, s)\ntrên chuỗi:\nAAD ‖ pad16 ‖ C ‖ pad16 ‖\nlen(AAD) ‖ len(C)",
           fill=ACCENT_FILL, stroke=ACCENT, size=12)
    s.line(740, 95, 860, 180)
    s.line(740, 328, 800, 280)
    s.line(1100, 130, 1000, 180)
    s.rect(1080, 215, 140, 60, "Tag T\n(128 bit)", fill=WARN_FILL, stroke=WARN, weight="bold")
    s.line(1030, 245, 1080, 245)
    s.rect(800, 380, 420, 56, "Kết quả lưu: 02 ‖ N ‖ C ‖ T  (29 byte phụ thêm)", fill=FILL,
           weight="bold", size=14)
    s.path("M640,356 V408 H800", color=LINE)
    s.line(1150, 275, 1150, 380)
    return s.render()


def aead_decrypt() -> str:
    s = Svg(1240, 380)
    s.text(620, 22, "Giải mã ChaCha20-Poly1305: xác thực trước, giải mã sau", 16, weight="bold")
    steps = [
        (30, "Đọc blob:\n02 ‖ N ‖ C ‖ T", FILL, LINE),
        (225, "Định dạng hợp lệ?\nđộ dài > 13 byte?", FILL, LINE),
        (420, "ChaCha20(K, N, 0)\n→ khóa Poly1305", ACCENT_FILL, ACCENT),
        (615, "T' = Poly1305(AAD ‖ C …)\nAAD dựng lại từ ngữ cảnh", ACCENT_FILL, ACCENT),
        (810, "So sánh T' và T\nthời gian hằng", KEY_FILL, KEY),
        (1005, "Khớp: P = C ⊕\nChaCha20(K, N, 1..)", ACCENT_FILL, ACCENT),
    ]
    for x, label, f, st in steps:
        s.rect(x, 70, 175, 90, label, fill=f, stroke=st, size=13)
    for x, *_ in steps[:-1]:
        s.line(x + 175, 115, x + 195, 115)
    s.rect(420, 250, 560, 90,
           "DecryptionFailed: không trả ra byte bản rõ nào.\nNguyên nhân: bản mã/tag bị sửa, sai khóa, sai ngữ cảnh (chép sang\nbản ghi khác), sai byte định dạng",
           fill=WARN_FILL, stroke=WARN, size=13)
    s.line(312, 160, 470, 250, color=WARN)
    s.text(350, 215, "không", 12, color=WARN)
    s.line(897, 160, 820, 250, color=WARN)
    s.text(880, 215, "lệch", 12, color=WARN)
    return s.render()


def dinh_dang_ban_ma() -> str:
    s = Svg(1240, 300)
    s.text(620, 22, "Bản mã một trường lưu trong cột VARBINARY (ví dụ CCCD 12 chữ số → 41 byte)", 15,
           weight="bold")
    parts = [("định dạng\n1 byte", 110, FILL, LINE), ("nonce\n12 byte", 300, BLUE_FILL, BLUE),
             ("ciphertext\n12 byte (= độ dài bản rõ)", 360, ACCENT_FILL, ACCENT),
             ("tag Poly1305\n16 byte", 400, WARN_FILL, WARN)]
    x = 30
    for label, w, f, st in parts:
        s.rect(x, 50, w, 70, label, fill=f, stroke=st, rx=0, size=13, weight="bold")
        x += w
    hexes = [("02", 110), ("8faba8e1c0cfdf9eb81bdcc8", 300), ("8c40565e2713596c2b537dee", 360),
             ("02d5dac2646adb982ccc2fe9a81df8b3", 400)]
    x = 30
    for h, w in hexes:
        s.text(x + w / 2, 140, h, 12, mono=True, color=MUTED)
        x += w
    s.rect(30, 175, 1170, 50,
           "AAD (không lưu, dựng lại khi giải mã):  02 ‖ \"customers.national_id:3f2b0c4e11114222833394445555666\"",
           fill="#ffffff", dash=True, size=13, mono=True)
    s.text(615, 255, "Byte 01 = AES-256-GCM (dữ liệu trước ADR 0005, chỉ còn giải mã). Byte 02 = ChaCha20-Poly1305. Byte khác → từ chối.",
           13, color=MUTED)
    return s.render()


def phan_cap_khoa() -> str:
    s = Svg(1240, 520)
    s.text(620, 22, "Các khóa bí mật và khóa dẫn xuất trong hệ thống", 16, weight="bold")
    roots = [("DATA_ENC_KEY", 60), ("HMAC_INTEGRITY_KEY\n(+ khóa cũ theo phiên bản)", 170),
             ("BLIND_INDEX_KEY", 300), ("SESSION_SECRET", 400)]
    for label, y in roots:
        s.rect(30, y, 240, 76 if "\n" in label else 60, label, fill=WARN_FILL, stroke=WARN, size=13,
               weight="bold", mono="\n" not in label)
    s.text(150, 490, "Biến môi trường / Docker secret,\nkhông commit, ≥ 32 byte ngẫu nhiên", 12, color=MUTED)
    s.rect(340, 40, 220, 56, "HKDF-SHA256\ninfo = \".../chacha20-poly1305\"", fill=ACCENT_FILL,
           stroke=ACCENT, size=12)
    s.rect(340, 110, 220, 46, "SHA-256 (định dạng cũ)", size=12)
    s.line(270, 90, 340, 68)
    s.line(270, 90, 340, 133)
    s.rect(630, 40, 250, 56, "K_field 256 bit\nChaCha20-Poly1305 (định dạng 2)", fill=KEY_FILL,
           stroke=KEY, size=12)
    s.rect(630, 110, 250, 46, "K_legacy: AES-256-GCM, chỉ giải mã", size=12)
    s.line(560, 68, 630, 68)
    s.line(560, 133, 630, 133)
    s.rect(950, 30, 270, 130,
           "Mã hóa: CCCD, thu nhập,\ntài khoản nhận, khóa TOTP,\ndữ liệu chờ xác nhận OTP.\nMỗi lần mã hóa: nonce mới;\nmỗi bản tin: khóa Poly1305 riêng",
           size=12)
    s.line(880, 68, 950, 80)
    s.rect(340, 180, 220, 56, "HMAC-SHA256", fill=ACCENT_FILL, stroke=ACCENT, size=13)
    s.line(270, 208, 340, 208)
    s.rect(630, 180, 590, 56, "snapshot_hash + key_version trên approval_decisions (SR08, SUC02)",
           size=12)
    s.line(560, 208, 630, 208)
    s.rect(340, 300, 220, 56, "HMAC-SHA256", fill=ACCENT_FILL, stroke=ACCENT, size=13)
    s.line(270, 330, 340, 328)
    s.rect(630, 300, 590, 56, "customers.national_id_hash: tra cứu CCCD không cần giải mã (blind index)",
           size=12)
    s.line(560, 328, 630, 328)
    s.rect(340, 400, 220, 56, "HMAC-SHA256", fill=ACCENT_FILL, stroke=ACCENT, size=13)
    s.line(270, 430, 340, 428)
    s.rect(630, 400, 590, 56, "sessions.token_hash, mã OTP SMS: CSDL chỉ giữ mã băm có khóa",
           size=12)
    s.line(560, 428, 630, 428)
    return s.render()


def chuoi_bam() -> str:
    s = Svg(1240, 330)
    s.text(620, 22, "Nhật ký kiểm toán dạng chuỗi băm: hash_n = SHA-256(hash_(n-1) ‖ JSON chuẩn hóa(seq, actor, action, …))",
           14, weight="bold")
    xs = [30, 330, 630, 930]
    labels = [("seq 56", "LOAN_APPROVE", "prev = …", "hash = 68c1…"),
              ("seq 57", "(hành động gốc)", "prev = 68c1…", "hash = 106a…"),
              ("seq 58", "DISBURSE_REQUEST", "prev = 106a…", "hash = 2666…"),
              ("seq 59", "…", "prev = 2666…", "hash = …")]
    for x, (a, b, c, d) in zip(xs, labels):
        s.rect(x, 50, 260, 120, fill="#ffffff", stroke=LINE)
        s.text(x + 130, 70, a, 13, weight="bold")
        s.text(x + 130, 96, b, 13, mono=True)
        s.text(x + 130, 124, c, 12, mono=True, color=MUTED)
        s.text(x + 130, 150, d, 12, mono=True, color=ACCENT)
    for x in xs[:-1]:
        s.line(x + 260, 145, x + 300, 120, color=ACCENT)
    s.rect(330, 200, 260, 110, fill=WARN_FILL, stroke=WARN)
    s.text(460, 220, "Kẻ có quyền root sửa seq 57", 13, weight="bold", color=WARN)
    s.text(460, 248, "action = LOGIN_FAIL", 13, mono=True, color=WARN)
    s.text(460, 276, "SHA-256 tính lại ≠ hash đã lưu", 12, color=WARN)
    s.text(460, 298, "→ kiểm tra báo hỏng tại seq 57", 12, color=WARN, weight="bold")
    s.rect(630, 200, 580, 110,
           "Tính lại cả hash của 57 thì hash mới ≠ prev của 58 → báo hỏng tại 58.\nMuốn che giấu phải tính lại mọi bản ghi phía sau. Tài khoản ứng dụng\nkhông có quyền UPDATE/DELETE trên audit_logs.",
           fill=FILL, size=12)
    return s.render()


DIAGRAMS = {
    "h-kien-truc": kien_truc,
    "h-use-case": use_case,
    "h-tuan-tu-dang-nhap": seq_dang_nhap,
    "h-tuan-tu-dang-ky-totp": seq_dang_ky_totp,
    "h-tuan-tu-ma-hoa-truong": seq_ma_hoa_truong,
    "h-tuan-tu-giai-ngan": seq_giai_ngan,
    "h-chacha20-trang-thai": chacha_state,
    "h-aead-ma-hoa": aead_encrypt,
    "h-aead-giai-ma": aead_decrypt,
    "h-dinh-dang-ban-ma": dinh_dang_ban_ma,
    "h-phan-cap-khoa": phan_cap_khoa,
    "h-chuoi-bam": chuoi_bam,
}

if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[2:])
    for name, fn in DIAGRAMS.items():
        if only and name not in only:
            continue
        (out / f"{name}.svg").write_text(fn(), encoding="utf-8")
        print("wrote", name)
