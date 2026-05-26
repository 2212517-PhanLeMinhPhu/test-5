import json
import pandas as pd

# 1. Đọc file JSON
file_path = "Quan trắc thực địa (1).json"
with open(file_path, "r", encoding="utf-8") as f:
    data = json.load(f)

parsed_data = []

# 2. Duyệt qua từng bản ghi dữ liệu và xử lý khớp Key-Value
for item in data:
    # Lấy thời gian chung
    thoi_gian = item.get("Thời gian")
    stt = item.get("STT")
    
    # Khởi tạo mặc định
    nhiet_do = None
    do_am = None
    
    # Trường hợp 1: Nếu là trạm không khí (STT là 5 hoặc chứa key tempKK)
    if "tempKK" in item:
        nhiet_do = float(item.get("tempKK"))
        do_am = float(item.get("humiKK"))
    
    # Trường hợp 2: Các trạm thực địa đo đất, nước (Sử dụng key tiếng Việt)
    else:
        # Check cả 2 trường hợp "Nhiệt Độ" (viết hoa chữ Đ) và "Nhiệt độ" (viết thường chữ đ)
        raw_temp = item.get("Nhiệt Độ") or item.get("Nhiệt độ")
        raw_humi = item.get("Độ ẩm")
        
        if raw_temp is not None:
            nhiet_do = float(raw_temp)
        if raw_humi is not None:
            do_am = float(raw_humi)
            
    # Lưu lại kết quả sau khi đã đồng bộ hóa key
    parsed_data.append({
        "STT": stt,
        "Thời gian": thoi_gian,
        "Nhiệt độ (°C)": nhiet_do,
        "Độ ẩm (%)": do_am,
        "EC": item.get("EC"),
        "PH": item.get("PH"),
        "N": item.get("N"),
        "P": item.get("P"),
        "K": item.get("K"),
        "soil_ASKK": item.get("soil_ASKK")
    })

# 3. Chuyển đổi thành DataFrame để dễ quản lý, trích xuất hoặc vẽ biểu đồ
df = pd.DataFrame(parsed_data)

# Hiển thị thử 5 dòng đầu tiên sau khi sửa code
print(df.head())

# (Tùy chọn) Xuất ra file Excel sạch đẹp nếu bạn cần
# df.to_excel("data_da_xu_ly.xlsx", index=False)
