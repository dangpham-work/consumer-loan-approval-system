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

## Phát sinh khi cài đặt (ticket #3, #4)

- [ ] **Khóa tạm do đăng nhập sai (UC01 3c)**: chỉ đặt `users.locked_until` (15 phút), không đổi `status` sang LOCKED. `status = LOCKED` dành cho Quản trị viên khóa thủ công (UC04 2b), nên hết hạn khóa tạm không vô tình mở khóa một tài khoản bị Quản trị viên khóa.
- [ ] **Bảng `sessions`**: thêm `stage` (SETUP: đăng nhập lần đầu; MFA: đã qua mật khẩu, chờ TOTP; FULL: phiên đầy đủ) và `otp_failed_attempts` (sai 3 lần thì hủy phiên, UC02 3b).
- [ ] **Bảng `users`**: thêm `must_change_password` (tài khoản PENDING phải đổi mật khẩu tạm trước khi đăng ký TOTP) và `totp_last_step` (chống dùng lại mã TOTP). `totp_secret_enc` mã hóa AES-GCM bằng DATA_ENC_KEY.
- [ ] **Bảng `employees`**: chỉ có họ tên, email, chi nhánh (đúng các trường UC04 bước 2); bỏ `employee_code`, `dob`, `phone`. Tên đăng nhập nhân viên do Quản trị viên đặt và phải bắt đầu bằng chữ cái, để không trùng với tên đăng nhập của khách hàng (số điện thoại).
- [ ] **Vai trò CUSTOMER** nằm trong `user_roles` như các vai trò khác; quyền "O" của khách hàng được cấp trong `role_permissions`, còn phạm vi sở hữu kiểm tra ở tầng nghiệp vụ (SR04). Ô "M" không được cấp `CUSTOMER_VIEW_PII`.
- [ ] **Mã quyền**: ô gộp trong ma trận RBAC tách thành từng mã: `APPLICATION_VERIFY` và `APPLICATION_REQUEST_INFO`; `LOAN_APPROVE` và `LOAN_REJECT`.
- [ ] **UC04 2d**: Quản trị viên không được tự gán cho mình bất kỳ vai trò nào ngoài ADMIN (bị chặn với 403, ghi `ROLE_ASSIGN_DENIED`). Ngoài ra không tài khoản nào được giữ ADMIN cùng vai trò nghiệp vụ cho vay, để hai quản trị viên không gán chéo cho nhau. Tạo nhân viên và đổi vai trò đều yêu cầu nhập lại TOTP (step-up, 4.2.4).
- [ ] **Sai mật khẩu và sai mã TOTP dùng chung bộ đếm khóa tài khoản** (SR01), bộ đếm chỉ về 0 khi đăng nhập xong hẳn: biết mật khẩu cũng không thể đoán mã TOTP qua nhiều lần đăng nhập.
- [ ] **`audit_logs.detail`**: cột chi tiết không nhạy cảm (ví dụ vai trò trước/sau, UC04). Chỉ đưa vào nội dung băm khi có giá trị, nên hash của các bản ghi cũ không đổi.
- [ ] **Quản trị viên đầu tiên** tạo bằng lệnh `python -m loan_system.create_admin`; mật khẩu tạm in ra một lần.
- [ ] **Giới hạn tần suất (SR12)**: đăng nhập và xác thực OTP 10 lượt mỗi phút mỗi địa chỉ IP; nộp hồ sơ vay và tải giấy tờ 30 lượt mỗi phút mỗi người dùng. Bộ đếm trong bộ nhớ tiến trình; chạy nhiều worker thì cần bộ đếm dùng chung (Redis).
- [ ] **Che dữ liệu (SR07)**: giữ 3 ký tự đầu và 3 ký tự cuối (079******234). Mỗi hồ sơ vay tối đa 20 file tải lên (kể cả file đã bị thay thế).
- [ ] **`loan_applications.code`**: cho phép NULL, chỉ cấp khi nộp (UC12 bước 9), duy nhất khi có giá trị; số thứ tự lấy từ SEQUENCE `loan_application_code_seq`. Thêm `consent_at`, `consent_version` (đồng ý xử lý dữ liệu cá nhân gắn với từng hồ sơ vay, SR14) và `created_at`. Các cột `received_by`, `appraised_by`, `policy_id`, `annual_rate`, `created_by`, `deleted_at` thêm ở ticket dùng đến chúng.
- [ ] **`application_documents`**: thêm `content_type` (kiểu thật theo magic bytes), `size_bytes`, `uploaded_by`, `replaced_at` (UC13 2a: file cũ được đánh dấu thay thế, không xóa).
- [ ] **`customers.employer`**: thêm cột nơi làm việc (M03 bước 2 có trường này nhưng lược đồ 4.1.2d không có).
- [ ] **Số tiền trả hằng tháng ước tính (M03 bước 1)**: tính theo lãi suất trần 28%/năm (hạng C), vì lúc lập hồ sơ vay chưa có Hạng.
- [ ] **Nộp hồ sơ vay**: bắt buộc đủ thông tin bước 2 (trừ nơi làm việc) và cả 4 loại giấy tờ (CCCD 2 mặt, chứng minh thu nhập, hóa đơn điện/nước). CCCD không đổi được nữa khi khách hàng đã từng nộp một hồ sơ vay.
- [ ] **Màn hình Jinja2** (M01, M03, M09) chưa làm trong ticket #3, #4: mới có API.

## Phát sinh khi cài đặt (ticket #5)

- [ ] **`loan_applications`**: thêm `created_by`, `received_by` (FK → employees), `need_info_message`, `need_info_items`, `need_info_deadline` (UC15, BR11), `cancel_reason` (UC17).
- [ ] **`application_documents`**: thêm `review_verdict` (PASS/FAIL), `review_note`, `reviewed_by`, `reviewed_at` (UC14 bước 4). Chỉ xác nhận hợp lệ khi đủ 4 loại giấy tờ và mọi giấy tờ đang dùng đều Đạt.
- [ ] **Bảng mới `application_status_history`**: dòng thời gian trạng thái cho UC16 bước 3; mọi chuyển trạng thái đi qua bảng chuyển trạng thái 3.4a (UT06).
- [ ] **Bảng `notifications`** dùng từ ticket này: thông báo trong ứng dụng (`GET /notifications`), khách hàng nhận thêm SMS. Hồ sơ vay mới nộp báo cho mọi NV tín dụng; hồ sơ vay gửi lại sau bổ sung báo cho đúng Người tiếp nhận.
- [ ] **Bảng mới `otp_challenges`**: OTP qua SMS để khách hàng xác nhận thao tác do NV khởi tạo (lưu thông tin khách vãng lai, nộp hộ hồ sơ vay). Hết hạn 5 phút, sai 3 lần thì hủy, chỉ NV đã khởi tạo mới xác nhận được. Dữ liệu chờ xác nhận được mã hóa và xóa khi thử thách kết thúc. SMS nộp hộ nêu số tiền, kỳ hạn, tài khoản nhận (đã che); đổi các điều khoản đó sau khi gửi mã thì mã mất hiệu lực.
- [ ] **UC15**: khi bổ sung, chỉ sửa được đúng những mục NV đã yêu cầu (trường thông tin hoặc loại giấy tờ); số tiền, kỳ hạn, mục đích không nằm trong danh sách được yêu cầu. Quá hạn 15 ngày thì không sửa, không gửi lại được. Gửi lại thì mọi giấy tờ phải được đánh giá lại.
- [ ] **Che dữ liệu cho nhân viên**: nhân viên không thấy thu nhập (ô "M"); khách hàng không thấy mã nhân viên xử lý hồ sơ vay của mình.
- [ ] **UC14 2a**: Người tiếp nhận giữ hồ sơ vay cả khi hồ sơ quay lại sau bổ sung. Người tạo (nộp hộ) không được nhận hồ sơ vay mình tạo (403, ghi `SOD_VIOLATION`).
- [ ] **UC12 1a**: khách vãng lai được tạo kèm tài khoản PENDING (tên đăng nhập là số điện thoại, mật khẩu ngẫu nhiên không ai biết); việc khách vãng lai tự kích hoạt tài khoản để đăng nhập chưa làm.
- [ ] **Phạm vi xem của nhân viên**: nhân viên có APPLICATION_VIEW thấy mọi hồ sơ vay đã nộp (dữ liệu nhạy cảm đã che) và bản nháp do chính mình nộp hộ; không thấy bản nháp của khách hàng.

## Phát sinh khi cài đặt (ticket #6)

- [ ] **Kích hoạt chấm điểm**: chạy ngay sau khi NV tín dụng xác nhận hợp lệ, trong giao dịch riêng (thay cho EventBus bất đồng bộ của SD03). Lỗi ở bước chấm điểm không làm mất việc xác nhận; hồ sơ vay ở lại VERIFIED để chấm lại.
- [ ] **Luật loại trừ (BR01, BR03, BR04)** xét theo thứ tự tuổi 20–60 (tại ngày nộp), thu nhập tối thiểu 5 triệu, nợ nhóm 3 trở lên, DTI > 50% theo lãi suất trần; lưu lý do đầu tiên vi phạm. Luật loại trừ nằm trong mã, không nằm trong file mô hình.
- [ ] **Biên các khoảng của thẻ điểm (1.2.7)**: thu nhập < 7 triệu | 7 triệu đến dưới 15 triệu | 15–30 triệu (gồm 30) | trên 30 triệu; DTI ≤ 20% | ≤ 35% | ≤ 50%; thời gian làm việc 0 | 1–3 | từ 4 năm; tuổi 20–24 | 25–45 | 46–60.
- [ ] **Dữ liệu thay thế (hóa đơn điện/nước 12 tháng)** đi kèm phản hồi CIC giả lập, lưu ở `cic_reports.utility_late_payments`. Thiếu dữ liệu CIC thì yếu tố CIC tính như "chưa có lịch sử" (100) và yếu tố hóa đơn tính như "trễ 1–2 lần" (60).
- [ ] **CIC giả lập có kịch bản** theo chữ số cuối của CCCD (9: không phản hồi, 8: nhóm 3, 7: nhóm 2, 6: chưa có lịch sử, còn lại: nhóm 1). Hết thời gian chờ thì thử tối đa 3 lần với thời gian chờ 5, 10, 20 giây. Báo cáo CIC dưới 30 ngày của cùng khách hàng được dùng lại (chép sang hồ sơ vay mới, giữ `queried_at` gốc).
- [ ] **Bảng mới `scoring_models`** (`version`, `file_name`, `checksum`, `is_active`): mô hình thẻ điểm là file JSON trong `scoring_models/`, checksum SHA-256 đăng ký sẵn trong migration. File không khớp checksum (hoặc không đọc được) thì dừng chấm điểm, ghi `MODEL_INTEGRITY_FAIL` mức CRITICAL, báo mọi Quản trị viên (ST09). File được đánh dấu `-text` trong `.gitattributes` để git không đổi ký tự xuống dòng.
- [ ] **`credit_scores`**: `score`, `grade`, `model_version` cho phép NULL khi bị loại trừ (không chấm theo mô hình); thêm `dti` (theo lãi suất trần); `top_factors_json` đổi thành `factors_json` chứa điểm cả 7 yếu tố so với điểm tối đa, tối đa 3 yếu tố làm giảm điểm nhiều nhất (bỏ yếu tố không mất điểm) suy ra khi hiển thị (UC20). Một hồ sơ vay có thể có nhiều lần chấm, bản mới nhất có hiệu lực.
- [ ] **`approval_policies`** tạo ở ticket này với bảng lãi suất theo hạng và phí trả trước hạn; bản mặc định phiên bản 1 (20%/24%/28%, phí 3%). Số lượt phê duyệt theo khoảng hạn mức thêm ở ticket phê duyệt.
- [ ] **`loan_applications`**: thêm `annual_rate`, `policy_id` (chốt khi chấm điểm, vì lãi suất lấy từ đúng phiên bản chính sách đó), `cic_missing` (Thiếu dữ liệu CIC), `fraud_suspected` (CIC vượt khai báo trên 20% hoặc trên 1 triệu).
- [ ] **Lãi suất trần** lấy từ lãi suất hạng C của chính sách đang hiệu lực (không ghi cứng), để DTI của luật loại trừ và lãi suất theo hạng luôn cùng một phiên bản chính sách.
- [ ] **Checksum mô hình** được kiểm tra khi cần nạp mô hình, tức sau luật loại trừ (thứ tự UC18 bước 3–4): hồ sơ vay bị loại trừ không nạp mô hình nên không phát hiện file bị sửa ở lượt đó. Kết quả bị loại trừ không có phiên bản mô hình.
- [ ] **Lỗi bất ngờ khi chấm điểm** (ví dụ CIC trả dữ liệu ngoài miền giá trị): hoàn tác phần chấm điểm, ghi `SCORING_FAILED` mức CRITICAL; việc xác nhận hợp lệ vẫn giữ, hồ sơ vay ở VERIFIED chờ chấm lại.
- [ ] **Thông báo**: bị từ chối (loại trừ hoặc hạng D) thì báo khách hàng kèm lý do qua SMS và trong ứng dụng; chuyển Đang thẩm định thì báo mọi Chuyên viên thẩm định.
- [ ] **`GET /applications/{id}/score`** (UC20, quyền `CREDIT_SCORE_VIEW`): điểm, hạng, lý do loại trừ, điểm từng yếu tố, 3 yếu tố ảnh hưởng chính, phiên bản mô hình, lãi suất theo hạng, tóm tắt báo cáo CIC và các cờ.
