# Hệ thống quản lý và xét duyệt vay tín dụng tiêu dùng

Hệ thống quản lý toàn bộ vòng đời một khoản vay tín chấp tiêu dùng cá nhân (5–100 triệu đồng, 6–36 tháng) tại một công ty tài chính giả định: từ lúc nộp hồ sơ vay, chấm điểm, thẩm định, phê duyệt, giải ngân đến thu nợ và tất toán.

## Ngôn ngữ

### Khách hàng và hồ sơ

**Khách hàng** (Customer):
Cá nhân có nhu cầu vay, gồm thông tin định danh, nghề nghiệp, thu nhập và nhà ở.
_Tránh_: hồ sơ khách hàng, người vay

**Thông tin khách hàng**:
Tập dữ liệu mô tả một Khách hàng, tồn tại độc lập với mọi hồ sơ vay.
_Tránh_: hồ sơ khách hàng, hồ sơ của tôi

**Hồ sơ vay** (LoanApplication):
Một đề nghị vay của Khách hàng, đi qua các bước từ nháp đến khi giải ngân, bị từ chối hoặc bị hủy.
_Tránh_: hồ sơ (đứng một mình), đơn vay

**Khoản vay** (Loan):
Nghĩa vụ trả nợ phát sinh từ một Hồ sơ vay đã giải ngân. Chỉ tồn tại sau khi giải ngân.
_Tránh_: hợp đồng vay, hồ sơ

**Người tạo** (created_by):
Nhân viên tín dụng đã nộp hộ Hồ sơ vay tại quầy. Không có khi Khách hàng tự nộp.

**Người tiếp nhận** (received_by):
Nhân viên tín dụng đã kiểm tra và xác nhận Hồ sơ vay hợp lệ.

### Chấm điểm và thẩm định

**Báo cáo CIC** (CICReport):
Kết quả tra cứu lịch sử tín dụng của Khách hàng tại CIC (giả lập), gồm nhóm nợ cao nhất trong 24 tháng và nghĩa vụ trả nợ hằng tháng.

**Thiếu dữ liệu CIC**:
Cờ trên Hồ sơ vay khi CIC không phản hồi. Hồ sơ vay vẫn được chấm điểm, với yếu tố CIC tính như chưa có lịch sử tín dụng.

**Nhóm nợ** (debt group):
Phân loại chất lượng nợ từ 1 đến 5 theo số ngày quá hạn (BR09). Nhóm 3–5 là nợ xấu. Nhóm nợ độc lập với trạng thái của Khoản vay.

**Nghĩa vụ nợ hiện có**:
Tổng số tiền trả nợ hằng tháng của Khách hàng cho các khoản vay khác, lấy giá trị lớn hơn giữa số tự khai và số trong Báo cáo CIC. Khi thiếu Báo cáo CIC thì dùng số tự khai.

**DTI**:
Tỷ lệ (Nghĩa vụ nợ hiện có + số tiền trả mỗi kỳ của khoản vay mới) trên thu nhập hằng tháng.

**Luật loại trừ** (knock-out rule):
Điều kiện mà nếu vi phạm thì Hồ sơ vay bị từ chối ngay, không cần chấm điểm (tuổi, nhóm nợ, DTI).

**Điểm tín dụng** (CreditScore):
Kết quả chấm điểm của một Hồ sơ vay theo thẻ điểm 7 yếu tố (tối đa 1000 điểm), kèm hạng và các yếu tố ảnh hưởng chính.

**Hạng** (Grade):
Mức rủi ro A/B/C/D suy ra từ Điểm tín dụng. Hạng D bị từ chối tự động.

**Lãi suất theo hạng**:
Lãi suất năm hệ thống gán cho Hồ sơ vay dựa trên Hạng. Được chốt vào Hồ sơ vay và không đổi sau đó.
_Tránh_: lãi suất đề xuất

**Lãi suất trần**:
Lãi suất của hạng rủi ro nhất chưa bị từ chối (hạng C), dùng để tính DTI khi Hồ sơ vay chưa có Hạng.

**Cờ nghi ngờ gian lận** (fraud_suspected):
Dấu hiệu trên Hồ sơ vay báo cho chuyên viên thẩm định biết có nghi vấn, ví dụ nghĩa vụ nợ khai báo thấp hơn nhiều so với Báo cáo CIC.

**Tờ trình thẩm định** (AppraisalReport):
Đánh giá và đề xuất của chuyên viên thẩm định về một Hồ sơ vay, gồm hạn mức và kỳ hạn đề xuất.
_Tránh_: báo cáo thẩm định

### Phê duyệt và giải ngân

**Chính sách phê duyệt** (ApprovalPolicy):
Bộ quy định có phiên bản, gồm số lượt phê duyệt theo khoảng hạn mức, Lãi suất theo hạng và tỷ lệ Phí trả trước hạn. Mỗi Hồ sơ vay áp dụng đúng phiên bản đã chốt cho nó.

**Quyết định phê duyệt** (ApprovalDecision):
Ý kiến Phê duyệt, Từ chối hoặc Trả về của một Quản lý phê duyệt đối với một Hồ sơ vay.

**Phê duyệt kép**:
Yêu cầu hai Quản lý phê duyệt khác nhau cùng đồng ý đối với khoản vay trên 50 triệu (BR05). Hai người quyết định độc lập, không phân biệt thứ tự. Một Từ chối là đủ để từ chối, một Trả về làm vô hiệu mọi Quyết định phê duyệt trước đó.

**Trả về**:
Quyết định đưa Hồ sơ vay quay lại bước thẩm định để làm rõ. Khác với Từ chối vì Trả về không kết thúc Hồ sơ vay.

**Hồ sơ vay đang xử lý**:
Hồ sơ vay chưa đến trạng thái kết thúc (chưa bị từ chối, bị hủy hay đã giải ngân), kể cả bản nháp và hồ sơ vay bị khóa. Mỗi Khách hàng chỉ được có tối đa một Hồ sơ vay đang xử lý hoặc một Khoản vay chưa tất toán (BR02).

**Hồ sơ vay bị khóa** (LOCKED):
Hồ sơ vay bị đóng băng vì snapshot không khớp trước khi giải ngân. Chỉ có thể được hủy sau khi điều tra xong, không bao giờ được giải ngân.

**Kiểm soát viên** (Auditor):
Nhân viên giám sát độc lập, chỉ được đọc nhật ký và dữ liệu. Ngoại lệ có chủ đích duy nhất: được hủy Hồ sơ vay bị khóa sau khi điều tra xong.

**Phân tách nhiệm vụ** (SoD):
Nguyên tắc: Người tạo, Người tiếp nhận, người thẩm định, người phê duyệt và người giải ngân của cùng một Hồ sơ vay phải là những người khác nhau (BR06).
_Tránh_: maker–checker (chỉ là một trường hợp riêng)

**Snapshot**:
Bản chụp các trường quan trọng của Hồ sơ vay (số tiền, kỳ hạn, lãi suất, tài khoản nhận) tại thời điểm được phê duyệt, dùng để phát hiện mọi thay đổi trước khi giải ngân.

**Giải ngân** (Disbursement):
Một lần chuyển tiền vay cho Khách hàng. Một Hồ sơ vay có thể có nhiều lần giải ngân thất bại trước lần thành công.

### Thu nợ

**Lịch trả nợ** (RepaymentSchedule):
Danh sách các Kỳ trả nợ của một Khoản vay, tính theo phương pháp niên kim. Không thay đổi sau khi giải ngân: tiền trả thừa được ghi là trả trước cho các kỳ sau, chỉ Tất toán mới làm giảm gốc trước hạn.

**Kỳ trả nợ** (Installment):
Một lần trả nợ đến hạn gồm gốc và lãi, có ngày đến hạn riêng.
_Tránh_: đợt trả

**Quá hạn**:
Trạng thái của Kỳ trả nợ hoặc Khoản vay khi đã qua ngày đến hạn mà chưa trả đủ, tính từ ngày đầu tiên. Quá hạn không đồng nghĩa với chuyển nhóm nợ.

**Nợ xấu**:
Trạng thái của Khoản vay khi quá hạn trên 90 ngày (nhóm nợ 3 trở lên).

**Phí phạt chậm trả** (penalty):
Khoản tiền duy nhất phát sinh do trả chậm, tính theo ngày trên phần gốc và lãi còn nợ của Kỳ trả nợ quá hạn, với lãi suất bằng 150% lãi suất năm.
_Tránh_: lãi quá hạn, lãi phạt

**Lãi phát sinh**:
Lãi tính theo ngày trên dư nợ gốc còn lại, từ ngày đến hạn gần nhất đến ngày tất toán.

**Tất toán**:
Việc trả hết dư nợ gốc, lãi và phí để đóng Khoản vay, có thể đúng hạn hoặc trước hạn.

**Phí trả trước hạn**:
Tỷ lệ phần trăm trên dư nợ gốc còn lại, thu khi tất toán trước hạn. Được miễn khi tất toán trong kỳ cuối cùng.
