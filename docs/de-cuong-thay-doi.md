# Các chỗ cần sửa trong đề cương

Kết quả phiên hỏi đáp rà soát đề cương `De_cuong_OOAD_Vay_tin_dung_ban_dong_bo`. Mã (Q1–Q18) là số câu hỏi trong phiên đó. Thuật ngữ theo `CONTEXT.md`; lý do của các quyết định lớn nằm ở `docs/adr/`.

## Chương 1 – Quy tắc và công thức

- [ ] **BR02**: "hồ sơ vay đang xử lý" gồm các trạng thái DRAFT, SUBMITTED, NEED_INFO, VERIFIED, APPRAISING, PENDING_APPROVAL, APPROVED, LOCKED; Khoản vay ACTIVE, OVERDUE, BAD_DEBT cũng chặn tạo mới. REJECTED và CANCELLED không chặn, không có thời gian chờ (Q12).
- [ ] **BR06**: thêm "người tạo (nộp hộ)" vào danh sách người phải khác nhau (Q3).
- [ ] **BR10**: miễn phí trả trước hạn khi tất toán trong kỳ cuối (Q8).
- [ ] **1.2.8b**: nghĩa vụ nợ hiện có = max(khai báo, CIC); CIC vượt khai báo trên 20% hoặc trên 1 triệu thì gắn cờ nghi ngờ gian lận; thiếu CIC thì dùng số khai báo (Q6). Lúc chấm điểm tính DTI theo lãi suất trần (hạng C), lúc thẩm định tính lại theo lãi suất của hạng thật (Q9).
- [ ] **1.2.8c**: phí phạt tính trên phần gốc và lãi còn nợ của kỳ, tính lại từ đầu mỗi đêm. Chỉ có một khoản "phí phạt chậm trả", không có "lãi quá hạn" riêng (Q5).
- [ ] **1.2.8d**: lãi phát sinh = dư nợ gốc còn lại × lãi suất năm / 365 × số ngày (actual/365) (Q8).
- [ ] **Mục mới**: bảng lãi suất theo hạng A = 20%, B = 24%, C = 28%/năm, lưu trong Chính sách phê duyệt (Q2, Q10).
- [ ] **FR04.3** (MLScoringModel): ghi rõ nằm ngoài phạm vi demo. Demo gồm toàn bộ FR mức Cao cùng FR01.4 và FR04.4 (Q1).

## Chương 2 – Hoạt động, Use Case, RBAC

- [ ] **AD02 D01**: điều kiện chặn theo BR02 mới (Q12).
- [ ] **AD03 A04**: khi thiếu dữ liệu CIC, gắn cờ rồi **tiếp tục chấm điểm** (yếu tố CIC tính như "Chưa có lịch sử"), không chuyển thẳng sang APPRAISING (Q17).
- [ ] **AD04**: bỏ fork/join. Hai quản lý quyết định độc lập, không phân biệt thứ tự: một Từ chối là từ chối ngay; một Trả về thì về APPRAISING và vô hiệu các quyết định trước; đủ 2 Phê duyệt thì APPROVED (Q11).
- [ ] **AD06b A07** và **UC28 bước 4**: thứ tự phân bổ là phí phạt → lãi kỳ quá hạn → gốc kỳ quá hạn → lãi kỳ hiện tại → gốc kỳ hiện tại (Q5).
- [ ] **UC09**: thêm luồng thay thế — NV tín dụng tạo Customer kèm UserAccount PENDING cho khách vãng lai, gửi OTP để khách xác nhận đồng ý (Q3).
- [ ] **UC11**: đổi tên thành "Tra cứu thông tin khách hàng" (Q7).
- [ ] **UC12 1a**: ghi nhận `created_by` khi NV nộp hộ (Q3).
- [ ] **UC18 1a**: sửa theo AD03 A04 mới (Q17).
- [ ] **UC18 4a**: tác vụ hằng đêm tự chấm lại các hồ sơ vay ở VERIFIED quá 1 giờ; checksum vẫn sai thì tiếp tục cảnh báo Quản trị viên (Q14).
- [ ] **UC18**: gán lãi suất theo hạng sau khi chấm điểm và chốt vào hồ sơ vay (Q2).
- [ ] **UC22 bước 5**: tính lại DTI theo lãi suất của hạng thật (Q9).
- [ ] **UC23 6a**: sửa theo quy tắc gộp của AD04 (Q11).
- [ ] **UC25 7b**: lỗi tạm thời thì thử lại với cùng dữ liệu; cần đổi tài khoản nhận thì NV giải ngân hủy hồ sơ vay (APPROVED → CANCELLED) và khách nộp hồ sơ vay mới (Q13).
- [ ] **UC28 4a**: tiền trả thừa ghi là trả trước cho các kỳ sau (lãi trước, gốc sau), không tính lại lịch trả nợ; muốn giảm gốc thì dùng Tất toán (Q18).
- [ ] **UC29**: tính lại nhóm nợ mỗi đêm từ số ngày quá hạn của kỳ quá hạn lâu nhất (Q4).
- [ ] **SUC01**: kiểm tra thêm `created_by` (Q3).
- [ ] **Ma trận RBAC**: thêm quyền `APPLICATION_LOCK_RESOLVE` cho Kiểm soát viên; việc NV giải ngân hủy hồ sơ vay APPROVED dùng quyền `DISBURSE` (Q16).
- [ ] **Mục 2.2.1**: sửa mô tả Kiểm soát viên — chỉ đọc, trừ một ngoại lệ có chủ đích là hủy hồ sơ vay bị khóa (Q16).

## Chương 3–4 – Trạng thái và CSDL

- [ ] **3.4a**: thêm LOCKED → CANCELLED (Kiểm soát viên, bắt buộc lý do, ghi nhật ký) và APPROVED → CANCELLED (NV giải ngân, "hủy để lập lại") (Q13).
- [ ] **3.4b T02**: bỏ "nhóm nợ 2" khỏi hành động. `debt_group` tách khỏi `status`: quá hạn 1–9 ngày là OVERDUE nhưng vẫn nhóm 1 (Q4).
- [ ] **`loan_applications`**: thêm cột `annual_rate` và `created_by` (Q2, Q3).
- [ ] **`approval_policies`**: thêm bảng lãi suất theo hạng và tỷ lệ phí trả trước hạn (Q8, Q10).
- [ ] **Mục 4.1.2 và 4.1.2d**: đổi CSDL từ PostgreSQL sang SQL Server (ADR 0003). Ánh xạ kiểu: UUID → UNIQUEIDENTIFIER, NUMERIC → DECIMAL, VARCHAR/TEXT → NVARCHAR, BYTEA → VARBINARY(MAX), TIMESTAMPTZ → DATETIMEOFFSET, BOOLEAN → BIT, JSONB → NVARCHAR(MAX) + CHECK ISJSON, INET → VARCHAR(45), BIGSERIAL → BIGINT IDENTITY.
- [ ] **Mục 4.1.2e**: quyền CSDL viết theo SQL Server (`DENY UPDATE, DELETE` cho `app_rw`); trigger bằng T-SQL; kết nối `Encrypt=yes`; sao lưu bằng `BACKUP DATABASE … WITH ENCRYPTION` thay cho `pg_dump`.
- [ ] **Mục 4.2.1, 4.2.3 (biểu đồ triển khai)**: nút Database server là SQL Server, cổng 1433 thay cho 5432.
- [ ] **Mục 5.1**: bảng công cụ đổi PostgreSQL thành SQL Server 2022 + pyodbc (ODBC Driver 18).
- [ ] **Biểu đồ lớp 1**: thêm `annualRate`, `createdBy` vào LoanApplication; thêm lãi suất theo hạng và phí trả trước hạn vào ApprovalPolicy (Q2, Q3, Q8).

## Phát sinh khi cài đặt (ticket #1)

- [ ] **Bảng mới `registration_requests`**: lưu yêu cầu đăng ký chờ xác minh OTP (UC09 bước 3–4); OTP lưu dạng HMAC, hạn 5 phút, sai 3 lần thì hủy.
- [ ] **Bảng mới `sessions`**: phiên đăng nhập lưu phía máy chủ (chỉ lưu mã băm token) thay cho JWT, để đăng xuất và hết hạn 15 phút (SR11) có hiệu lực ngay.
- [ ] **`users.username` của khách hàng = số điện thoại**.
- [ ] **`customers.national_id_enc`, `national_id_hash`**: UC09 không thu thập CCCD, nên hai cột này sẽ được thêm ở ticket #4 và cho phép NULL cho đến khi khách hàng nộp hồ sơ vay đầu tiên (đề cương đang đặt NOT NULL).
- [ ] **Mục 5.1**: môi trường dev dùng ODBC Driver 17 (máy phát triển), container dùng ODBC Driver 18.
