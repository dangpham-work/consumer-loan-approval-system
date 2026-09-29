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

## Phát sinh khi cài đặt (ticket #16)

- [ ] **Màn hình M09** mở rộng có API: `GET /admin/roles`, `GET /admin/permissions` (bảng quyền hiện có), `POST /admin/roles` (tạo vai trò kèm tập quyền ban đầu), `PUT /admin/roles/{code}/permissions` (đổi tập quyền), `GET /admin/policies`, `POST /admin/policies` (lưu phiên bản chính sách mới). Cả bốn thao tác ghi đều yêu cầu step-up OTP (UC02) như UC04.
- [ ] **UC05 bước 4 (quy tắc xung đột quyền)**: cụ thể hóa "ví dụ" trong đề cương thành một nhóm cố định `{APPRAISAL_SUBMIT, LOAN_APPROVE, DISBURSE}` (dây chuyền thẩm định → phê duyệt → giải ngân của BR06): một vai trò không được giữ từ hai quyền trở lên trong nhóm này. Không làm bảng cặp quyền xung đột cấu hình được vì đề cương không yêu cầu và ma trận RBAC vốn đã cố định theo migration.
- [ ] **UC05**: tạo vai trò (`POST /admin/roles`) nhận luôn tập quyền ban đầu trong một lần gọi, không tách bước "tạo vai trò trống rồi gán quyền" vì đề cương mô tả một luồng chính duy nhất cho cả hai trường hợp. Chưa làm xóa vai trò (không có trong luồng UC05).
- [ ] **UC06**: `POST /admin/policies` kiểm tra các khoảng hạn mức (phủ kín 5–100 triệu, không chồng lấn, không bị hở, BR05) trước khi lưu; sai thì 400 và không ghi gì. Lưu thành công thì tạo `approval_policies` phiên bản mới (số phiên bản tự tăng) và vô hiệu hóa phiên bản trước đó trong cùng giao dịch (chỉ mục lọc `is_active`). Chưa làm `approver_role_id` (đã ghi ở ticket #7: chỉ có một vai trò phê duyệt).
