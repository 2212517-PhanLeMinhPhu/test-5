import math

def calculate_vpd(temperature: float, humidity: float) -> float:
    """
    Tính toán Áp suất hơi hụt (VPD - Vapor Pressure Deficit)
    
    Tham số:
    temperature (float): Nhiệt độ không khí (°C)
    humidity (float): Độ ẩm tương đối của không khí (%)
    
    Trả về:
    float: Giá trị VPD (kPa) được làm tròn 2 chữ số thập phân
    """
    # Khống chế lỗi dữ liệu đầu vào nếu có
    if humidity < 0 or humidity > 100:
        raise ValueError("Độ ẩm phải nằm trong khoảng từ 0% đến 100%")

    # 1. Tính Áp suất hơi bão hòa (VPsat) bằng công thức Tetens (kPa)
    vp_sat = 0.61078 * math.exp((17.27 * temperature) / (temperature + 237.3))
    
    # 2. Tính VPD thực tế dựa trên độ ẩm thực tế (VPact)
    # VPD = VPsat - VPact = VPsat * (1 - RH / 100)
    vpd = vp_sat * (1.0 - (humidity / 100.0))
    
    return round(vpd, 2)

# ==========================================
# VÍ DỤ CHẠY THỬ KIỂM TRA
# ==========================================
if __name__ == "__main__":
    # Giả sử nhiệt độ nhà kính Đà Lạt là 25°C và độ ẩm là 65%
    test_temp = 25.0
    test_rh = 65.0
    
    result_vpd = calculate_vpd(test_temp, test_rh)
    
    print(f"--- KẾT QUẢ KIỂM TRA ---")
    print(f"🌡️ Nhiệt độ: {test_temp}°C")
    print(f"💧 Độ ẩm: {test_rh}%")
    print(f"🎯 Chỉ số VPD tính được: {result_vpd} kPa")
