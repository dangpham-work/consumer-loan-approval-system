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
- [ ] **Màn hình Jinja2** (M03, M09) chưa làm trong ticket #3, #4: mới có API. M01 làm ở ticket #22, M02 và M03 ở ticket #23.

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

## Phát sinh khi cài đặt (ticket #7)

- [ ] **Màn hình M06** mới có API (như các màn hình khác): `POST /applications/{id}/appraisal/open` (mở hồ sơ vay để thẩm định), `GET /applications/{id}/appraisal/dti` (DTI tính lại khi đổi hạn mức, kỳ hạn), `POST /applications/{id}/appraisal` (nộp tờ trình).
- [ ] **Người thẩm định** (`loan_applications.appraised_by`): chuyên viên mở hồ sơ vay đầu tiên trở thành người thẩm định duy nhất; chuyên viên khác mở thì 409, nộp tờ trình khi chưa mở thì 403.
- [ ] **SUC01** dùng chung cho mọi bước (nhận hồ sơ vay, thẩm định): vi phạm thì 403, ghi `SOD_VIOLATION` mức WARNING kèm tên bước và báo mọi Kiểm soát viên (SUC01 2a). Thẩm định chặn Người tạo và Người tiếp nhận.
- [ ] **VIEW_PII**: M06 hiển thị CCCD và thu nhập đầy đủ cho người có `CUSTOMER_VIEW_PII`, mỗi lần mở ghi `VIEW_PII` (đối tượng là Khách hàng), dùng chung ngưỡng cảnh báo SR09.
- [ ] **Trình xem giấy tờ có watermark (MUC06)**: `GET /applications/{id}/appraisal/documents/{docId}`, chỉ người thẩm định của hồ sơ vay, trong lúc hồ sơ vay đang thẩm định (các vai trò chỉ xem dữ liệu đã che – ô "M" – không tải được ảnh CCCD). Ảnh JPEG/PNG được in chéo tên đăng nhập, họ tên (bỏ dấu), thời điểm xem, mã hóa lại (bỏ EXIF); ảnh không đọc được thì 409, không trả file gốc. PDF trả nguyên nội dung kèm header `X-Watermark` để trình xem phủ lên. Mỗi lượt xem giấy tờ tính là một lượt `VIEW_PII` (chung ngưỡng SR09); `Cache-Control: no-store`. Thêm thư viện Pillow. Trình xem giấy tờ cho NV tín dụng ở UC14 chưa làm.
- [ ] **Tờ trình** (`appraisal_reports`): thêm `dti` (theo lãi suất của Hạng thật, hạn mức và kỳ hạn đề xuất); bỏ UNIQUE theo hồ sơ vay vì bị Trả về thì thẩm định lại, tờ trình mới nhất có hiệu lực. Đề xuất từ chối không cần hạn mức, kỳ hạn (UC22 4b). Nhận xét ≥ 20 ký tự; hạn mức đề xuất ≤ số tiền yêu cầu và trong khoảng BR02. Cờ nghi ngờ gian lận của chuyên viên lưu trên tờ trình, tách với cờ hệ thống gắn khi chấm điểm.
- [ ] **UC22 5a**: đề xuất duyệt mà DTI > 50% thì không lưu (400). Hạn mức đề xuất không vượt số tiền yêu cầu, nên chỉ rút ngắn kỳ hạn mới có thể làm DTI vượt ngưỡng.
- [ ] **Chốt chính sách phê duyệt**: phiên bản chính sách đã chốt từ lúc chấm điểm (ticket #6); khi nộp tờ trình chốt thêm `loan_applications.required_approvals` theo hạn mức đề xuất (đề xuất từ chối thì theo số tiền yêu cầu). Bảng mới `approval_policy_tiers` (khoảng hạn mức → số lượt phê duyệt) thay cho các cột `min_amount`, `max_amount`, `required_approvals` của `approval_policies`; bản mặc định: 5–50 triệu cần 1, trên 50 triệu cần 2 (BR05). Chưa có `approver_role_id` (chỉ có một vai trò phê duyệt). Hạn mức không thuộc khoảng nào của chính sách thì 409.
- [ ] **Chưa làm**: chuyên viên thẩm định yêu cầu bổ sung (UC22 4a, APPRAISING → NEED_INFO).

## Phát sinh khi cài đặt (ticket #8)

- [ ] **Màn hình M07** mới có API: `GET /applications/{id}/approval` (hồ sơ vay đã che, điểm tín dụng, tờ trình có hiệu lực, lịch sử quyết định, "cần N – đã có M", `can_decide` để ẩn nút khi vi phạm SoD), `POST /applications/{id}/approve` (quyền `LOAN_APPROVE`, ý kiến không bắt buộc), `POST /applications/{id}/reject` và `/return` (quyền `LOAN_REJECT`, lý do bắt buộc ≥ 10 ký tự).
- [ ] **`approval_decisions`**: thêm `appraisal_report_id` (quyết định gắn với tờ trình được quyết định), `reason_group` (UC24 bước 2: FINANCIAL_CAPACITY, CREDIT_HISTORY, FRAUD_SUSPECTED, OTHER), `key_version` (phiên bản khóa HMAC_INTEGRITY_KEY, 4.2.5). UNIQUE(`application_id`, `approver_id`) đổi thành UNIQUE(`appraisal_report_id`, `approver_id`): bị Trả về thì có tờ trình mới và cùng Quản lý được quyết định lại. Bảng chỉ ghi thêm (`DENY UPDATE, DELETE` cho `app_rw`); Trả về làm vô hiệu các quyết định trước vì chúng thuộc tờ trình cũ, không phải sửa bản ghi.
- [ ] **`appraisal_reports.seq`** (IDENTITY): thứ tự tờ trình của một hồ sơ vay, tờ trình có seq lớn nhất có hiệu lực (thời điểm có thể trùng nhau).
- [ ] **`loan_applications`**: thêm `approved_amount`, `approved_term` (hạn mức, kỳ hạn theo tờ trình được duyệt, là số tiền sẽ giải ngân).
- [ ] **Snapshot (SR08)**: mã hồ sơ vay, mã số hồ sơ, số tiền yêu cầu, hạn mức và kỳ hạn được duyệt, lãi suất theo hạng, tài khoản nhận (giải mã trong bộ nhớ), ghép theo thứ tự cố định với số đã chuẩn hóa; HMAC-SHA256 lưu trên quyết định làm hồ sơ vay được duyệt. Xoay khóa: `HMAC_INTEGRITY_KEY_VERSION` và `HMAC_INTEGRITY_OLD_KEYS` (JSON phiên bản → khóa cũ).
- [ ] **SUC01 ở bước phê duyệt**: chặn Người tạo, Người tiếp nhận, người thẩm định và người đã quyết định trên tờ trình hiện hành (403, `SOD_VIOLATION`, báo Kiểm soát viên).
- [ ] **Tờ trình đề xuất từ chối** không có hạn mức, kỳ hạn nên không Phê duyệt được (409); Quản lý chỉ Từ chối hoặc Trả về.
- [ ] **Thông báo**: duyệt thì báo khách hàng (SMS và trong ứng dụng, nêu hạn mức, kỳ hạn) và mọi NV giải ngân; từ chối thì báo khách hàng chỉ nhóm lý do (không kèm mô tả); trả về thì báo người thẩm định kèm nội dung cần làm rõ; chưa đủ số lượt thì báo các Quản lý phê duyệt (UC23 6a).
- [ ] **Quy tắc gộp AD04** đã có ở tầng miền; test phê duyệt kép (TC02) và khóa lạc quan trả 409 làm ở ticket #9. Kiểm tra snapshot trước giải ngân (SUC02) làm ở ticket #10.

## Phát sinh khi cài đặt (ticket #9)

- [ ] **UC23 6b (khóa lạc quan)**: `GET /applications/{id}/approval` trả thêm `version` (cột `loan_applications.version`); `POST .../approve`, `.../reject`, `.../return` bắt buộc gửi lại `version` đó (thiếu thì 400). Hồ sơ vay không còn "Chờ phê duyệt" thì vẫn 409 như trước; còn chờ nhưng phiên bản khác thì 409 "Hồ sơ vay vừa được cập nhật, vui lòng tải lại" và không ghi quyết định nào.
- [ ] **Mọi quyết định đều tăng `version`**, kể cả phê duyệt đầu tiên của khoản trên 50 triệu, khi hồ sơ vay vẫn "Chờ phê duyệt" (6a). Nhờ vậy Quản lý thứ hai đang mở M07 cũ phải tải lại để thấy quyết định vừa có rồi mới quyết định. Hai người vẫn quyết định độc lập, không phân biệt thứ tự (AD04), nhưng luôn trên lịch sử quyết định mới nhất. Khóa dòng (UPDLOCK) có từ ticket #8 vẫn giữ: hai yêu cầu cùng phiên bản đến đồng thời thì yêu cầu sau chờ, đọc lại dòng đã đổi phiên bản và nhận 409.
- [ ] **Tổ hợp quyết định cho khoản cần hai phê duyệt**: Phê duyệt + Phê duyệt thì duyệt (snapshot chỉ ký trên quyết định thứ hai); Phê duyệt + Từ chối thì từ chối; Phê duyệt + Trả về thì về thẩm định; Từ chối hoặc Trả về ngay từ đầu thì kết thúc luôn, người thứ hai nhận 409. Trả về làm vô hiệu phê duyệt trước; tờ trình mới lại cần đủ hai phê duyệt, kể cả của người đã quyết định trên tờ trình cũ. Một Quản lý không phê duyệt hai lần (403, SUC01).
- [ ] **SUC01 được kiểm tra trước phiên bản**: người vi phạm phân tách nhiệm vụ gửi phiên bản cũ vẫn nhận 403 và bị ghi `SOD_VIOLATION`, không lẩn vào 409.
- [ ] **UC23 6a**: "thông báo quản lý thứ hai" gửi cho mọi Quản lý phê duyệt còn được quyết định trên tờ trình hiện hành, trừ người vừa phê duyệt và những người bị SUC01 chặn (Người tạo, Người tiếp nhận, người thẩm định). Không có khái niệm "quản lý thứ hai được chỉ định" trong đề cương.
- [ ] **Chưa làm UC23 3a (vượt thẩm quyền)**: chỉ có một vai trò phê duyệt (ghi ở ticket #7), nên mọi Quản lý phê duyệt đều đủ thẩm quyền với mọi hạn mức.

## Phát sinh khi cài đặt (ticket #16)

- [ ] **Màn hình M09** mở rộng có API: `GET /admin/roles`, `GET /admin/permissions` (bảng quyền hiện có), `POST /admin/roles` (tạo vai trò kèm tập quyền ban đầu), `PUT /admin/roles/{code}/permissions` (đổi tập quyền), `GET /admin/policies`, `POST /admin/policies` (lưu phiên bản chính sách mới). Cả bốn thao tác ghi đều yêu cầu step-up OTP (UC02) như UC04.
- [ ] **UC05 bước 4 (quy tắc xung đột quyền)**: cụ thể hóa "ví dụ" trong đề cương thành một nhóm cố định `{APPRAISAL_SUBMIT, LOAN_APPROVE, DISBURSE}` (dây chuyền thẩm định → phê duyệt → giải ngân của BR06): một vai trò không được giữ từ hai quyền trở lên trong nhóm này. Không làm bảng cặp quyền xung đột cấu hình được vì đề cương không yêu cầu và ma trận RBAC vốn đã cố định theo migration.
- [ ] **UC05**: tạo vai trò (`POST /admin/roles`) nhận luôn tập quyền ban đầu trong một lần gọi, không tách bước "tạo vai trò trống rồi gán quyền" vì đề cương mô tả một luồng chính duy nhất cho cả hai trường hợp. Chưa làm xóa vai trò (không có trong luồng UC05).
- [ ] **UC06**: `POST /admin/policies` kiểm tra các khoảng hạn mức (phủ kín 5–100 triệu, không chồng lấn, không bị hở, BR05) trước khi lưu; sai thì 400 và không ghi gì. Lưu thành công thì tạo `approval_policies` phiên bản mới (số phiên bản tự tăng) và vô hiệu hóa phiên bản trước đó trong cùng giao dịch (chỉ mục lọc `is_active`). Chưa làm `approver_role_id` (đã ghi ở ticket #7: chỉ có một vai trò phê duyệt).

## Phát sinh khi cài đặt (ticket #10)

- [ ] **Màn hình M08** mới có API: `GET /applications/{id}/disbursement` (SUC01, SUC02 rồi hiển thị: toàn vẹn, thời điểm phê duyệt, người nhận, tài khoản đã che, số tiền, lãi suất, kỳ hạn, có lệnh đang chờ hay không) và `POST /applications/{id}/disburse` (quyền `DISBURSE`, kèm mã TOTP; theo thứ tự SD06: SUC01, SUC02 rồi mới xác thực lại TOTP, sai thì 403, sai 3 lần thì hủy phiên). Chưa có số tiền bằng chữ; chưa có tên ngân hàng vì lược đồ chỉ lưu số tài khoản nhận.
- [ ] **SUC02** dựng snapshot từ chính các cột của hồ sơ vay (kể cả `approved_amount`, `approved_term` và tài khoản nhận giải mã trong bộ nhớ), cả lúc ký khi phê duyệt lẫn lúc đối chiếu. Được gọi khi mở M08 và khi giải ngân. Không khớp (hoặc thiếu trường, bản mã tài khoản bị sửa) thì APPROVED → LOCKED, ghi `INTEGRITY_FAIL` mức CRITICAL, báo mọi Kiểm soát viên và Quản lý phê duyệt, trả 409. Phiên bản khóa không còn trong cấu hình thì 409, không khóa hồ sơ vay.
- [ ] **SUC01 ở bước giải ngân**: chặn Người tạo, Người tiếp nhận, người thẩm định và mọi người đã ra quyết định phê duyệt trên hồ sơ vay.
- [ ] **Trigger T-SQL `trg_loan_applications_approved_immutable`** (BR07, 4.1.2e): hồ sơ vay APPROVED, DISBURSED, LOCKED không đổi được mã, khách hàng, số tiền, kỳ hạn, mục đích, tài khoản nhận, lãi suất, chính sách, hạn mức và kỳ hạn được duyệt; chỉ trạng thái đổi tiếp được. Bảng có trigger nên ánh xạ ORM tắt `implicit_returning`. ST04 mô phỏng kẻ tấn công có quyền quản trị CSDL tắt trigger rồi sửa `requested_amount`: snapshot vẫn phát hiện.
- [ ] **`disbursements`**: thêm `failure_reason`, `created_at`, `completed_at`; `performed_by` NOT NULL; tài khoản nhận mã hóa AES-GCM với ngữ cảnh riêng của lệnh. Chỉ một lệnh PENDING hoặc SUCCESS cho mỗi hồ sơ vay (chỉ mục duy nhất có điều kiện). Lệnh được lưu và commit trước khi gọi cổng thanh toán; lỗi tạm thời thì lệnh ở PENDING (409 "thử lại"), thử lại dùng lại đúng lệnh và idempotency key; cổng từ chối thì FAILED (409, thông điệp cố định; lý do của cổng lưu ở `failure_reason` và nhật ký) và không lập lệnh mới được nữa vì tài khoản nhận không đổi được (Q13: hủy hồ sơ vay để lập lại). Thông báo NV tín dụng khi FAILED và hủy để lập lại thuộc ticket #11. Tiền đã chuyển mà hồ sơ vay vừa đổi trạng thái trong lúc gọi cổng: lệnh vẫn ghi SUCCESS kèm mã giao dịch, ghi `DISBURSE_ORPHAN` mức CRITICAL và báo Kiểm soát viên để đối soát. Cổng thanh toán thật phải bảo đảm mỗi idempotency key chỉ được thực hiện một lần kể cả khi nhận đồng thời.
- [ ] **Cổng thanh toán giả lập** (`adapters/payment.py`): cùng idempotency key thì trả lại kết quả cũ, không chuyển tiền lần hai; test đặt kịch bản lỗi tạm thời hoặc từ chối tài khoản.
- [ ] **`loans`**: `annual_rate` DECIMAL(5,4) như `loan_applications` (đề cương ghi NUMERIC(5,2)); `debt_group` bắt đầu ở 1. Hạn mức, kỳ hạn của khoản vay lấy từ `approved_amount`, `approved_term`.
- [ ] **Bảng mới `loan_contracts`** (`loan_id`, `content` VARBINARY(MAX), `sha256`, `created_at`): hợp đồng PDF lưu trong CSDL để cùng giao dịch với khoản vay và lịch trả nợ (UC26: lỗi giữa chừng thì hoàn tác). PDF sinh bằng fpdf2, chữ bỏ dấu tiếng Việt (phông chuẩn của PDF không đủ dấu; muốn có dấu cần đóng gói một phông TTF), không nén và lấy ngày giải ngân làm ngày tạo nên cùng điều khoản cho cùng file. CCCD và tài khoản nhận trong hợp đồng được che.
- [ ] **Ngày đến hạn** tính từ ngày giải ngân theo UTC, như mọi ngày khác trong hệ thống.
- [ ] **BR02**: Khoản vay ACTIVE, OVERDUE, BAD_DEBT chặn lập hồ sơ vay mới và khóa đổi thu nhập (ticket #17), dùng chung một kiểm tra.
- [ ] **Thông báo**: giải ngân thành công thì báo khách hàng (SMS và trong ứng dụng: số tiền, tài khoản đã che, kỳ trả nợ đầu tiên). Gửi hợp đồng và lịch trả nợ cho khách hàng (UC26 bước 6), xem lịch trả nợ, tải PDF thuộc ticket #12.

## Phát sinh khi cài đặt (ticket #11)

- [ ] **`POST /applications/{id}/disbursement/cancel`** (quyền `DISBURSE`, không cần OTP hay SoD): NV giải ngân hủy hồ sơ vay Đã phê duyệt để lập lại (APPROVED → CANCELLED), chỉ khi hồ sơ vay đã có một lệnh giải ngân FAILED (`NoFailedDisbursement` nếu chưa); lệnh PENDING (lỗi tạm thời) vẫn chỉ thử lại được, không hủy được. Không cần SoD hay OTP vì lệnh FAILED đã là bằng chứng người thực hiện lượt giải ngân trước đã qua SUC01/SUC02.
- [ ] **Thông báo `DISBURSE_FAILED`**: cổng thanh toán từ chối lệnh giải ngân thì báo đúng NV tín dụng đã tiếp nhận hồ sơ vay (`received_by`), hoặc mọi NV tín dụng nếu hồ sơ vay do khách tự nộp — cùng mẫu với `APPLICATION_RESUBMITTED` (ticket #5).
- [ ] **`POST /applications/{id}/resolve-lock`** (quyền `APPLICATION_LOCK_RESOLVE`, chỉ Kiểm soát viên): hủy hồ sơ vay Bị khóa sau khi điều tra xong (LOCKED → CANCELLED), lý do bắt buộc tối thiểu 10 ký tự, ghi vào `cancel_reason` và dòng lịch sử trạng thái, hành động kiểm toán `APPLICATION_LOCK_RESOLVE`. Không cần OTP: Kiểm soát viên vốn chỉ đọc, đây là ngoại lệ duy nhất (CONTEXT.md) nên không cần bước xác thực lại như UC04/UC05.
- [ ] **Thử lại khi lỗi tạm thời (UC25 7a)**: đã có sẵn từ ticket #10 (lệnh PENDING, cùng idempotency key); ticket #11 không đổi hành vi này, chỉ thêm hai lối ra cho FAILED và LOCKED.

## Phát sinh khi cài đặt (ticket #12)

- [x] **Màn hình M04** (trang web ở ticket #24) có API: `GET /loans/{id}/schedule` (bảng kỳ, dư nợ gốc, số tiền cần thanh toán hiện tại gồm cả phí phạt của các kỳ đã đến hạn, kỳ kế tiếp), `GET /loans/{id}/schedule/pdf` (lịch trả nợ PDF, cùng kiểu hợp đồng ở ticket #10: chữ bỏ dấu) và `POST /loans/{id}/payments`. Dùng lại quyền `PAYMENT_RECORD` (Khách hàng, NV tín dụng), không thêm quyền mới; khách hàng chỉ thấy khoản vay của mình (khoản vay người khác trả 404).
- [ ] **Kênh thanh toán suy ra từ loại người dùng**, không do client gửi: Khách hàng luôn ONLINE qua cổng thanh toán giả lập; NV tín dụng luôn COUNTER, bắt buộc mã phiếu thu (lưu vào `external_ref`), không gọi cổng. Để khách hàng không tự khai "đã nộp tại quầy".
- [ ] **Bảng mới `payments`** (`external_ref` UNIQUE: mã giao dịch cổng hoặc mã phiếu thu) và **`payment_allocations`** (khoản thanh toán, kỳ, thành phần PENALTY/INTEREST/PRINCIPAL, số tiền) để tra cứu phân bổ. **`installments.penalty_paid`**: phần `paid_amount` đã trả phí phạt, lưu riêng vì phí phạt tính lại mỗi đêm có thể phát sinh sau khi kỳ đã được trả một phần.
- [ ] **UC28 bước 4**: phân bổ theo kỳ tăng dần, mỗi kỳ trả hết phí phạt → lãi → gốc rồi mới sang kỳ sau; nhiều kỳ quá hạn thì kỳ cũ nhất trả hết trước. Trả thừa tự chuyển thành trả trước cho kỳ sau (Q18). Tổng vượt quá tổng còn lại của mọi kỳ thì 400: lịch trả nợ không đổi sau khi giải ngân, giảm gốc trước hạn là Tất toán (ticket #14).
- [ ] **UC28 3b**: cùng `external_ref` với cùng khoản vay và số tiền là xác nhận trùng, trả lại đúng khoản thanh toán cũ, không phân bổ lại; `external_ref` đã gắn với khoản thanh toán khác thì 409. Trực tuyến: M04 gửi `idempotency_key` sinh một lần cho mỗi lượt thanh toán, gửi lại thì cổng trả lại mã giao dịch cũ và không thu tiền hai lần.
- [ ] **UC28 3a**: cổng từ chối thì 409, không ghi nhận gì, ghi nhật ký `PAYMENT_FAILED` mức WARNING. Cổng tạm thời không phản hồi thì 409 "thử lại" (không lưu lượt thu đang chờ như giải ngân: chưa có tiền nào được ghi nhận).
- [ ] **Trạng thái kỳ (3.4c)**: trả một phần kỳ Đến hạn thì PARTIAL (T05); kỳ Chưa đến hạn được trả trước một phần vẫn UPCOMING; kỳ Quá hạn chỉ rời OVERDUE khi trả đủ (T08).
- [ ] **UC28 tiền điều kiện**: chỉ khoản vay ACTIVE, OVERDUE nhận thanh toán; BAD_DEBT chuyển thu hồi nợ (3.4b T09, ngoài phạm vi) nên 409. Dư nợ gốc về 0 thì SETTLED và gửi xác nhận tất toán (`LOAN_SETTLED`, T05). Chuyển OVERDUE → ACTIVE khi đã trả hết các kỳ quá hạn (T03) thuộc ticket #13.

## Phát sinh khi cài đặt (ticket #13)

- [ ] **Kích hoạt**: `uv run python -m loan_system.run_nightly_job`, do bộ lập lịch của hệ điều hành (cron, Task Scheduler) gọi lúc 00:30; "hôm nay" là ngày theo UTC như mọi ngày khác trong hệ thống. Không có API kích hoạt tác vụ (Timer không phải người dùng). Test đóng vai Bộ lập lịch bằng cách chạy `NightlyJob` trên cùng ứng dụng rồi quan sát kết quả qua REST API.
- [ ] **Chạy lại không cộng dồn** thay cho tiền điều kiện "tác vụ chưa chạy cho ngày hiện tại" của UC29: phí phạt tính lại từ đầu, các chuyển trạng thái chỉ xảy ra một lần, mỗi mốc nhắc nợ chỉ gửi một lần. Lô 500 là 500 khoản vay (không phải 500 kỳ), để trạng thái và nhóm nợ của một khoản vay luôn được tính trong cùng giao dịch với các kỳ của nó.
- [ ] **1.2.8c**: phí phạt = (gốc + lãi còn nợ của kỳ) × 150% × lãi suất năm / 365 × số ngày quá hạn, tính lại mỗi đêm; phí phạt đã trả không bao giờ bị lấy lại khi cơ sở tính giảm sau một lần trả một phần.
- [ ] **3.4c**: kỳ UPCOMING có ngày đến hạn đã qua (đêm đến hạn bị lỡ) chuyển thẳng sang OVERDUE. **3.4b**: mỗi thay đổi trạng thái hoặc nhóm nợ của khoản vay ghi `LOAN_STATUS_CHANGE` (Nợ xấu mức WARNING) cùng giao dịch; chuyển Nợ xấu báo mọi Quản lý phê duyệt (`LOAN_BAD_DEBT`, "Quản lý" của AD06a A06). Khoản vay Nợ xấu vẫn được tính phí phạt, nhóm nợ và nhắc nợ.
- [ ] **UC28 / 3.4b T03**: thanh toán hết các kỳ quá hạn thì khoản vay về ACTIVE, nhóm nợ 1 (cài ở dịch vụ thanh toán, cùng giao dịch với khoản thanh toán).
- [ ] **UC30**: bảng mới `payment_reminders` (kỳ, mốc, thời điểm gửi) là "lưu trạng thái gửi" (bước 4). Mốc quá hạn là mốc gần nhất đã tới (1/7/15/30 ngày): đêm bị lỡ thì lần chạy sau gửi bù mốc vừa qua, một lần. Nội dung gồm mã hồ sơ vay đã che, kỳ, số tiền còn phải trả và hạn thanh toán, không có liên kết. SMS lỗi thì thử lại 2 lần rồi bỏ qua tin đó; số tin lỗi ghi trong nhật ký `OVERDUE_JOB`.
- [ ] **BR11**: hồ sơ vay NEED_INFO quá `need_info_deadline` chuyển CANCELLED (lý do "Quá hạn bổ sung hồ sơ (BR11)", không có người thực hiện), ghi `APPLICATION_AUTO_CANCEL` và báo khách hàng (`APPLICATION_CANCELLED`).
- [ ] **UC18 4a**: hồ sơ vay VERIFIED quá 1 giờ kể từ lần chuyển VERIFIED gần nhất được chấm lại mỗi đêm; lỗi bất ngờ ghi `SCORING_FAILED`, file mô hình sai checksum thì cảnh báo Quản trị viên lại. CIC vẫn được tra cứu trước khi kiểm tra checksum (thứ tự của SD03), nên mỗi đêm có thể có một lượt tra cứu CIC thừa cho hồ sơ vay kẹt vì mô hình.

## Phát sinh khi cài đặt (ticket #14)

- [ ] **UC31 bước 2**: `GET /loans/{id}/payoff-quote` (quyền `LOAN_SETTLE`) trả báo giá tại ngày hiện tại: dư nợ gốc, lãi còn nợ của các kỳ đã đến hạn, lãi phát sinh, phí phạt chưa trả, phí trả trước hạn, tổng và `quoted_on`. Kỳ đã đến hạn mà chưa trả đủ (kể cả quá hạn) phải trả đủ lãi theo lịch; lãi phát sinh (1.2.8d) chỉ tính trên gốc của các kỳ chưa đến hạn, từ ngày đến hạn gần nhất (hoặc ngày giải ngân), vì gốc quá hạn đã chịu phí phạt. Lãi đã trả trước cho kỳ chưa đến hạn (UC28 4a) được trừ vào lãi phát sinh; phần vượt quá không được hoàn.
- [ ] **Phí trả trước hạn**: tỷ lệ lấy theo phiên bản chính sách phê duyệt hồ sơ vay đã chốt (ADR 0001), tính trên dư nợ gốc còn lại. BR10: miễn khi mọi kỳ trừ kỳ cuối đã đến hạn, hoặc không còn kỳ nào chưa đến hạn.
- [ ] **UC31 bước 3–4**: `POST /loans/{id}/settlement` (số tiền, `quoted_on`, mã phiếu thu hoặc `idempotency_key` như UC28) thu tiền và chống ghi nhận trùng như UC28. Đủ số tiền tất toán thì kỳ đã đến hạn thành PAID, các kỳ còn lại CANCELLED, khoản vay SETTLED (3.4b T06, T07), ghi `LOAN_SETTLE` và `LOAN_STATUS_CHANGE`, gửi xác nhận tất toán (`LOAN_SETTLED`). Phí trả trước hạn là thành phần phân bổ mới `FEE` (migration 0012).
- [ ] **UC31 2a**: `quoted_on` khác hôm nay thì 409, không thu tiền. **3a**: số tiền nhỏ hơn số tiền tất toán thì ghi nhận như thanh toán kỳ thông thường; lớn hơn thì 400. Khoản vay BAD_DEBT hoặc SETTLED thì 409, như UC28.
- [x] **Màn hình**: ticket này chỉ gồm API; báo giá và tất toán trên M04 làm ở ticket #24.

## Phát sinh khi cài đặt (ticket #18)

- [ ] **UC32**: `GET /reports/statistics` (quyền `REPORT_VIEW`, đã gán cho APPROVER từ ma trận RBAC ở ticket #3, không cần migration mới) trả trọn bộ chỉ tiêu của M11 trong một lần gọi — đề cương chỉ liệt kê một bộ biểu đồ cố định cho màn hình này, không có khái niệm "loại báo cáo" khác cần chọn riêng. Tham số `from`, `to` (ngày, bắt buộc); quá 12 tháng thì 400 (UC32 2a), ngày kết thúc trước ngày bắt đầu cũng 400.
- [ ] **Phạm vi tổng hợp**: hồ sơ vay tính theo `submitted_at` trong kỳ (số hồ sơ theo trạng thái, tỷ lệ duyệt/từ chối, thời gian xử lý trung bình từ nộp đến quyết định đầu tiên trong `application_status_history`); khoản vay (dư nợ, nhóm nợ, tỷ lệ quá hạn) tính trên các khoản giải ngân trong kỳ (`disbursed_at`), lấy `outstanding_principal`/`debt_group` hiện tại — hệ thống không lưu lịch sử dư nợ theo thời điểm nên không dựng lại được đúng số dư tại `to`.
- [ ] **`GET /reports/statistics/export`** (`format=CSV|PDF`, mặc định CSV): ghi log `REPORT_EXPORT`. "Excel" cài đặt bằng CSV có BOM UTF-8 để Excel đọc đúng tiếng Việt (cùng cách làm CSV của ticket #15, không thêm phụ thuộc xlsx); PDF dùng fpdf2, chữ bỏ dấu như hợp đồng (ticket #10). Báo cáo chỉ có số liệu tổng hợp (đếm, tổng tiền, tỷ lệ), không có tên khách hàng hay mã hồ sơ vay (SR07).
- [ ] **Không có bảng mới**: mọi chỉ tiêu tính trực tiếp từ các bảng đã có (`loan_applications`, `application_status_history`, `disbursements`, `loans`, `credit_scores`).
- [ ] **Màn hình**: dự án chưa có tầng Jinja2, nên ticket này chỉ gồm API (như ticket #14).

## Phát sinh khi cài đặt (ticket #22)

- [ ] **Đường dẫn trang HTML**: mọi trang nằm dưới `/app` (đăng nhập `/app/login`, trang chủ `/app`, `/` chuyển hướng về `/app`) để không trùng đường dẫn REST API. Tầng giao diện (`loan_system/web`) gọi thẳng tầng dịch vụ và dùng chung cookie phiên với API; test qua TestClient trên các trang HTML, cùng seam với REST API.
- [ ] **CSRF**: kiểu double-submit, cookie `csrf` ngẫu nhiên (HttpOnly, Secure, SameSite=Strict) và trường ẩn `csrf` trong mọi biểu mẫu POST; thiếu hoặc sai thì 403. Nút "Hiện" và "Tiếp tục làm việc" gọi REST API bằng `fetch`, dựa vào cookie phiên SameSite=Strict như các lời gọi API khác.
- [ ] **Menu theo vai trò**: mỗi mục gắn một quyền (và loại tài khoản nếu cần): Nộp hồ sơ vay và Khoản vay của tôi cho Khách hàng, Hàng đợi hồ sơ vay (`APPLICATION_VIEW`) cho nhân viên, Quản trị (`USER_MANAGE`), Nhật ký kiểm toán (`AUDIT_VIEW`), Báo cáo thống kê (`REPORT_VIEW`). M06, M07, M08 mở từ hàng đợi (M05), không có mục riêng. Trang chủ tạm thời chỉ chào người dùng; M02 và M05 thay trang này ở ticket #23, #25 (đã làm).
- [ ] **Đếm ngược hết phiên**: cảnh báo 2 phút trước khi hết 15 phút không hoạt động (SR11), nút "Tiếp tục làm việc" gọi `GET /auth/session` để gia hạn; hết giờ thì chuyển về màn hình đăng nhập.
- [ ] **Trang lỗi**: 400/403/404/409/429 dưới `/app` hiện trang lỗi chung, không lộ chi tiết kỹ thuật; đường dẫn ngoài `/app` vẫn trả JSON như cũ. Chưa đăng nhập hoặc phiên hết hạn thì chuyển về `/app/login` kèm thông báo. Thông báo góc trên chọn bằng khóa cố định (`?notice=`), không hiển thị chuỗi tùy ý từ URL.
- [ ] **UC03**: mới có đổi mật khẩu tạm khi đăng nhập lần đầu. Tầng nghiệp vụ chưa có đổi mật khẩu thường và quên mật khẩu, nên M01 chưa có hai chức năng này. Đăng ký TOTP hiện khóa dạng chữ và URI `otpauth://`, chưa có mã QR vì chưa có thư viện tạo QR.

## Phát sinh khi cài đặt (ticket #23)

- [ ] **Đường dẫn M02, M03**: trang chủ khách hàng là `/app`. Biểu mẫu 4 bước dùng mỗi bước một trang: `/app/applications/new` (bước 1, tạo bản nháp), rồi `/app/applications/{id}/loan`, `/finance`, `/documents`, `/confirm`. Chi tiết và dòng thời gian trạng thái (UC16) ở `/app/applications/{id}`, nút hủy (UC17) ở đó, có hộp thoại xác nhận. Mỗi bước lưu ngay vào bản nháp, nên khách hàng có thể dừng giữa chừng rồi tiếp tục từ trang chủ.
- [ ] **Bổ sung hồ sơ vay (UC15)**: dùng lại các bước 2 đến 4. Chỉ hiện ô nhập và nút tải lên cho những mục nhân viên tín dụng đã yêu cầu; bước 1 bị khóa vì số tiền, kỳ hạn, mục đích không thuộc danh sách được yêu cầu bổ sung.
- [ ] **Số CCCD và số tài khoản nhận** luôn hiển thị đã che, kể cả với chính khách hàng. Ô nhập để trống nghĩa là giữ giá trị đã khai.
- [ ] **Số tiền trả hằng tháng ước tính** ở bước 1 tính ngay trên trình duyệt (JavaScript, chỉ để tham khảo). Từ bước 2 trở đi hiển thị giá trị máy chủ tính bằng `Decimal`.
- [ ] **Trạng thái Bị khóa** hiển thị cho khách hàng là "Đang xử lý": không để lộ việc hồ sơ vay đang bị điều tra.
- [ ] **Kỳ đến hạn tiếp theo trên M02**: thêm `PaymentService.own_loans` (các Khoản vay chưa tất toán của khách hàng) và trường `next_due_amount` (số tiền còn phải trả của kỳ kế tiếp) trong `ScheduleView`. REST API `/loans/{id}/schedule` giữ nguyên.
- [ ] **Cập nhật thông tin cá nhân (UC10)** ở `/app/profile`, thêm mục menu "Thông tin cá nhân". Chỉ sửa được các trường như `PATCH /customers/me`. Đổi số điện thoại hoặc email cần OTP, chưa làm trên giao diện.
- [ ] **Lỗi nghiệp vụ trên trang HTML**: các lỗi đã ánh xạ ở `api/errors.py` (ví dụ không tìm thấy hồ sơ vay, ST01) hiện trang lỗi chung với cùng thông điệp khi xảy ra dưới `/app`. Lỗi của biểu mẫu (dữ liệu không hợp lệ, còn thiếu mục, file sai định dạng, trùng CCCD) hiện ngay trên biểu mẫu.

## Phát sinh khi cài đặt (ticket #25)

- [ ] **Đường dẫn M05, M06**: hàng đợi ở `/app/queue`. Nhân viên có `APPLICATION_VIEW` đăng nhập xong vào thẳng hàng đợi tại `/app`; Quản trị viên, Kiểm soát viên vẫn thấy trang chào. Chi tiết hồ sơ vay (M06) ở `/app/queue/{id}`: một trang chung cho mọi vai trò, chỉ hiện các thao tác người xem được làm (nhận xử lý, đánh giá giấy tờ, xác nhận hợp lệ, yêu cầu bổ sung, nhận thẩm định, lập tờ trình). M07, M08 (ticket #26) là trang riêng, mở bằng nút trên trang này.
- [ ] **Hàng đợi mặc định "Việc cần làm"** theo quyền: `APPLICATION_VERIFY` thấy Đã nộp, `APPRAISAL_SUBMIT` thấy Đang thẩm định, `LOAN_APPROVE` thấy Chờ phê duyệt, `DISBURSE` thấy Đã phê duyệt. Lọc được theo từng trạng thái hoặc "Tất cả", và tìm theo mã hồ sơ vay hoặc họ tên khách hàng. Danh sách hồ sơ vay (`ApplicationSummary`) có thêm họ tên khách hàng; REST API `GET /applications` giữ nguyên.
- [ ] **Nhân viên thấy trạng thái Bị khóa** đúng tên (khách hàng vẫn thấy "Đang xử lý").
- [ ] **Che dữ liệu trên M06**: CCCD và thu nhập luôn che, kể cả với chuyên viên thẩm định. Người có `CUSTOMER_VIEW_PII` bấm "Hiện" (gọi `POST /customers/{id}/reveal-pii`) mới thấy đầy đủ, mỗi lần bấm ghi `VIEW_PII`. Vì vậy trang web mở thẩm định bằng `AppraisalService.open(..., reveal=False)`: chỉ nhận thẩm định, không ghi `VIEW_PII`. REST API `POST /applications/{id}/appraisal/open` giữ nguyên (trả đầy đủ và ghi `VIEW_PII`).
- [ ] **ST03 trên giao diện**: tính trước các bước người xem đã tham gia (Người tạo, Người tiếp nhận, trường mới `appraised_by` trong `ApplicationView`, không có trong REST API) để ẩn thao tác vi phạm phân tách nhiệm vụ, kèm lời giải thích. Gửi thẳng yêu cầu thì tầng nghiệp vụ vẫn chặn (403, ghi `SOD_VIOLATION`).
- [ ] **DTI trên tờ trình**: đổi hạn mức hoặc kỳ hạn thì JavaScript gọi `GET /applications/{id}/appraisal/dti` để tính lại. Không có JavaScript thì bấm nút "Tính lại DTI". Tờ trình đã nộp hiển thị cho người có `CREDIT_SCORE_VIEW` (thêm `AppraisalService.report`).
- [ ] **Trình xem giấy tờ** ở `/app/queue/{id}/documents/{docId}`: nội dung nhúng thẳng vào trang, nên mỗi lần mở là đúng một lượt `VIEW_PII`. Ảnh đã in watermark ở máy chủ; PDF được phủ watermark bằng CSS. Trang trả `Cache-Control: no-store`. NV tín dụng vẫn chưa xem được nội dung giấy tờ khi kiểm tra (UC14) vì không có `CUSTOMER_VIEW_PII`, chỉ thấy loại, kích thước, thời điểm tải lên.
- [ ] **Nộp hộ trên giao diện (UC12 1a)** ở `/app/counter` (mục menu "Nộp hộ hồ sơ vay"): tìm khách hàng theo CCCD (`CUSTOMER_VIEW`) hoặc lập khách vãng lai. Khách vãng lai xác nhận đồng ý bằng OTP. Sau đó NV đi qua các bước 1–3 của M03 như khách hàng. Ở bước 4, khách hàng đọc mã OTP để đồng ý nộp hồ sơ vay, thay cho ô đánh dấu.

## Phát sinh khi cài đặt (ticket #26)

- [ ] **Đường dẫn M07, M08**: `/app/queue/{id}/approval` (quyền `LOAN_APPROVE`) và `/app/queue/{id}/disbursement` (quyền `DISBURSE`), mở bằng nút trên M06 khi hồ sơ vay ở trạng thái phù hợp. M07 vẫn mở được sau khi đã quyết định để xem lịch sử quyết định.
- [ ] **M07**: tóm tắt tờ trình, điểm tín dụng và CIC (dùng chung khối `_score.html` với M06), lịch sử quyết định (quyết định trên tờ trình cũ ghi "tờ trình cũ"), "Cần N – đã có M". Nút Duyệt chỉ hiện khi tờ trình đề xuất duyệt, có hộp thoại xác nhận. Từ chối, Trả về cần lý do ≥ 10 ký tự. `can_decide` sai thì ẩn cả ba nút kèm lời giải thích; gửi thẳng biểu mẫu vẫn bị chặn (403, `SOD_VIOLATION`). Phiên bản đã cũ (409) thì trang báo lỗi, ẩn các nút và có liên kết "Tải lại trang".
- [ ] **M08** hiện theo trạng thái. Đã phê duyệt: khối toàn vẹn xanh, thông tin chuyển tiền (tài khoản đã che), ô mã TOTP, hộp thoại xác nhận. Bị khóa (kể cả ngay khi mở trang mà snapshot không khớp, ST04): khối toàn vẹn đỏ, không có ô giải ngân. Lệnh giải ngân bị từ chối: báo "Giải ngân thất bại" và nút hủy hồ sơ vay để lập lại. Lệnh đang chờ: báo đang chờ, gửi lại dùng đúng lệnh cũ. Đã giải ngân: mã giao dịch, khoản vay, SHA-256 hợp đồng, lịch trả nợ và nút tải hợp đồng PDF.
- [ ] **API bổ sung**: `GET /applications/{id}/disbursement` có thêm trường `failed` (đã có lệnh bị từ chối). Mới có `GET /applications/{id}/contract` (quyền `DISBURSE`, trả hợp đồng PDF, 409 khi chưa giải ngân); trang web tải cùng nội dung ở `/app/queue/{id}/contract`. Khách hàng tải hợp đồng ở màn hình khoản vay (chưa làm).
- [ ] **Nút Giải ngân trên M06** hiện với mọi người có `DISBURSE` khi hồ sơ vay Đã phê duyệt; người đã tham gia các bước trước mở M08 thì bị chặn (403, `SOD_VIOLATION`), vì M06 không có danh sách Quản lý đã phê duyệt để ẩn nút trước.

## Phát sinh khi cài đặt (ticket #24)

- [ ] **Đường dẫn M04**: khách hàng mở danh sách khoản vay chưa tất toán ở `/app/loans` (mục menu "Khoản vay của tôi", liên kết từ trang chủ) rồi `/app/loans/{id}`. NV tín dụng mở M04 bằng nút trên M06 khi hồ sơ vay Đã giải ngân: `/app/queue/{id}/loan` chuyển tới khoản vay sinh ra từ hồ sơ vay đó (thêm `PaymentService.loan_of_application`). Lịch trả nợ PDF tải ở `/app/loans/{id}/schedule.pdf` (`Cache-Control: no-store`). Khoản vay của người khác báo 404; vai trò không có `PAYMENT_RECORD` báo 403.
- [ ] **Thanh toán trên M04**: khách hàng thanh toán trực tuyến, biểu mẫu mang sẵn `idempotency_key` ngẫu nhiên cho lượt thanh toán đó; gửi lại cùng biểu mẫu chỉ bị thu một lần. Cổng thanh toán từ chối thì trang cấp khóa mới (cổng nhớ kết quả theo khóa, gửi lại cùng khóa sẽ bị từ chối mãi); cổng không phản hồi hoặc nhập sai thì giữ khóa cũ vì tiền có thể đã được thu. NV tín dụng ghi nhận tiền mặt tại quầy, bắt buộc mã phiếu thu, không có khóa.
- [ ] **Tất toán trên M04**: người có `LOAN_SETTLE` thấy báo giá trong ngày (gốc, lãi đã đến hạn, lãi phát sinh, phí phạt, phí trả trước hạn, tổng) và nút Tất toán có hộp thoại xác nhận; biểu mẫu gửi đúng số tiền và ngày của báo giá đang xem. Báo giá của ngày khác thì 409, trang báo "Vui lòng xem lại số tiền tất toán" kèm báo giá mới. Khoản vay đã tất toán chỉ còn bảng kỳ (các kỳ còn lại "Đã hủy"). Bấm Tất toán (hoặc trả hết) hai lần thì yêu cầu thứ hai thấy khoản vay đã tất toán: trang báo "Đã tất toán khoản vay" thay vì báo lỗi, tiền chỉ bị thu một lần.
- [ ] **Khách hàng tải hợp đồng PDF** (ticket #26 để lại) vẫn chưa làm: M04 chỉ có lịch trả nợ PDF.
