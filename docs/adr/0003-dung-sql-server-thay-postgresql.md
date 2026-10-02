# Dùng SQL Server thay cho PostgreSQL

> **Đã bị thay thế bởi [ADR 0004](0004-chuyen-sang-mysql.md).** Giữ lại để ghi nhận lịch sử quyết định.

Đề cương ban đầu chọn PostgreSQL, nhưng nhóm quyết định dùng **SQL Server 2022** (bản Developer, chạy trong Docker) làm CSDL, truy cập qua SQLAlchemy với dialect `mssql+pyodbc`. Các cơ chế bảo mật tầng CSDL trong đề cương vẫn được giữ, chỉ đổi cách hiện thực: quyền chỉ ghi thêm cho nhật ký dùng `DENY UPDATE, DELETE` với `app_rw`; trigger chặn sửa hồ sơ vay đã duyệt viết bằng T-SQL; sao lưu mã hóa dùng `BACKUP … WITH ENCRYPTION` thay cho `pg_dump`. Mọi cột văn bản dùng NVARCHAR với collation tiếng Việt, còn cột mã băm dùng collation nhị phân. Đánh đổi: container nặng hơn (khoảng 2GB RAM), phải cài ODBC Driver 18, và không có sẵn kiểu JSON hay INET nên phải thay bằng NVARCHAR có kiểm tra ISJSON và VARCHAR(45). Toàn bộ test tích hợp chạy trên SQL Server thật, không dùng SQLite, để các kịch bản ST04 và ST08 phản ánh đúng CSDL triển khai.
