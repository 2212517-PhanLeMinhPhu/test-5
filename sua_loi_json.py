import json
import os

def fix_json_data(input_path, output_path):
    # 1. Kiểm tra file đầu vào có tồn tại không
    if not os.path.exists(input_path):
        print(f"Lỗi: Không tìm thấy file '{input_path}' ở thư mục hiện tại.")
        return

    # 2. Đọc dữ liệu từ file JSON
    print(f"Đang đọc dữ liệu từ file: {input_path}...")
    with open(input_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Lỗi định dạng file JSON: {e}")
            return

    count = 0  # Biến đếm số dòng đã sửa
    total_records = len(data)

    # 3. Duyệt qua từng bản ghi để kiểm tra và sửa đổi
    for item in data:
        # Chỉ xử lý các bản ghi có chứa đầy đủ cả 2 trường 'tempKK' và 'humiKK'
        if 'tempKK' in item and 'humiKK' in item:
            try:
                # Chuyển đổi giá trị chuỗi sang số thực để so sánh logic
                temp_val = float(item['tempKK'])
                humi_val = float(item['humiKK'])
                
                # BIỆN PHÁP LOGIC NHẬN BIẾT ĐẢO VỊ TRÍ:
                # Trong file thực tế, có các bản ghi ghi nhận tempKK lên đến 73°C - 89°C 
                # trong khi humiKK lại là 27% (Thực tế là Độ ẩm 73-89% và Nhiệt độ 27°C).
                # Do đó: Nếu tempKK > 65.0 và humiKK < 40.0 -> Chắc chắn đã bị đảo chỗ.
                if temp_val > 65.0 and humi_val < 40.0:
                    
                    # Thực hiện hoán đổi giá trị
                    item['tempKK'] = f"{humi_val:.2f}"
                    item['humiKK'] = f"{temp_val:.2f}"
                    count += 1
                    
                    # Lấy ID bản ghi để hiển thị log (nếu có trường ID)
                    record_id = item.get('_id', {}).get('$oid', 'N/A')
                    time_stamp = item.get('Thời gian', 'Không rõ thời gian')
                    print(f"-> Đã sửa bản ghi ID {record_id} [{time_stamp}]: "
                          f"Đảo lại thành Temp={item['tempKK']}°C, Humi={item['humiKK']}%")
                          
            except ValueError:
                # Bỏ qua dòng này nếu dữ liệu tempKK hoặc humiKK bị trống hoặc lỗi chữ không đổi được thành số
                continue

    # 4. Ghi dữ liệu sạch ra file mới
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("\n" + "="*50)
    print(f"HOÀN THÀNH XỬ LÝ!")
    print(f"- Tổng số bản ghi đã quét: {total_records}")
    print(f"- Số bản ghi bị lỗi đã đảo lại: {count}")
    print(f"- File dữ liệu mới đã được lưu tại: '{output_path}'")
    print("="*50)

# --- Chạy chương trình ---
if __name__ == "__main__":
    # Điền tên file đầu vào giống với file của bạn
    file_goc = "Quan trắc thực địa (1).json" 
    file_sach = "Quan_trac_thuc_dia_Da_Sua.json"
    
    fix_json_data(file_goc, file_sach)
