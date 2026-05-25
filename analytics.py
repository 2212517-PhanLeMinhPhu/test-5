import pandas as pd
import numpy as np

def predict_vpd_trend_v3(history_data, current_hour, vpd_min, vpd_max):
    """
    Thuật toán dự báo xu hướng nâng cao:
    - Sửa lỗi lệch pha/báo động giả khi đọc dữ liệu file quá khứ.
    - Dự báo thuần túy dựa trên biến động toán học (Độ dốc/Slope) của 3 mốc gần nhất.
    - Tự động phát hiện kẹt dữ liệu hoặc cảm biến bị treo.
    """
    if not history_data or len(history_data) < 3:
        return "📊 Hệ thống đang tích lũy thêm chu kỳ dữ liệu để phân tích xu hướng...", "normal"
    
    try:
        # Lấy thông số VPD của 3 điểm gần nhất (điểm 0 là mới nhất)
        v1 = float(history_data[0]["VPD (kPa)"])
        v2 = float(history_data[1]["VPD (kPa)"])
        v3 = float(history_data[2]["VPD (kPa)"])
        
        diff_1 = v1 - v2
        diff_2 = v2 - v3
        
        # Trường hợp 1: Dữ liệu đứng im hoàn toàn (Cảm biến bị đơ hoặc kẹt gửi)
        if abs(diff_1) < 0.005 and abs(diff_2) < 0.005:
            if v1 < vpd_min:
                return "🟦 CẢNH BÁO: Hiện trạng quá ẩm đang bị kẹt đứng im lâu. Cần bật quạt đối lưu lập tức.", "danger_blue"
            elif v1 > vpd_max:
                return "🟥 CẢNH BÁO: Hiện trạng khô nóng đang đứng im kéo dài. Cần kích hoạt hệ thống phun sương.", "danger_red"
            else:
                return "🟩 Xu hướng: Chỉ số VPD đang duy trì đi ngang rất ổn định trong dải lý tưởng.", "normal"
        
        # Tính toán độ dốc trung bình của chu kỳ biến động
        slope = (diff_1 + diff_2) / 2.0
        
        # Trường hợp 2: VPD thực tế đang nằm ngoài dải an toàn và tiếp tục diễn biến tệ đi
        if v1 > vpd_max and slope > 0.02:
            return f"🚨 [CẢNH BÁO SỚM] VPD đang vượt ngưỡng ({v1:.2f} kPa) và tiếp tục tăng khô gắt thêm. Nguy cơ cháy lá!", "danger_red"
        
        if v1 < vpd_min and slope < -0.02:
            return f"🚨 [CẢNH BÁO SỚM] Môi trường đang tích ẩm nặng ({v1:.2f} kPa) và có xu hướng ẩm ướt thêm. Nguy cơ nấm bệnh!", "danger_blue"
            
        # Trường hợp 3: Xu hướng biến động bình thường (Dành cho cả Realtime và dữ liệu tải file)
        if slope > 0.04:
            return "📈 Xu hướng: Nhiệt độ tăng / Độ ẩm giảm làm chỉ số VPD đang tăng nhanh (Khô dần).", "normal"
        elif slope < -0.04:
            return "📉 Xu hướng: Nhiệt độ giảm / Độ ẩm tăng làm chỉ số VPD đang sụt giảm nhanh (Ẩm lên).", "normal"
        else:
            return "🔄 Xu hướng: Biến động biên độ nhỏ, nằm trong tầm kiểm soát sinh học của cây.", "normal"
            
    except Exception as e:
        return f"🔄 Chỉ số xu hướng đang được chuẩn hóa toán học...", "normal"


def calculate_plant_stress_hours(df_data, vpd_min, vpd_max, mode_filter):
    """
    Thuật toán Agronomy: Tính toán áp lực sinh học (Stress điểm khí khổng) của cây trồng.
    Dựa trên tần suất xuất hiện và khoảng cách thời gian giữa các điểm dữ liệu sau gộp.
    """
    if df_data.empty or "VPD (kPa)" not in df_data.columns:
        return {"dry_hours": 0.0, "wet_hours": 0.0, "status": "Không đủ dữ liệu"}
    
    # Xác định số phút đại diện cho 1 điểm dữ liệu dựa theo chế độ lọc
    if "1 Ngày gần nhất" in mode_filter or "10 phút" in mode_filter:
        minutes_per_point = 10
    elif "1 Tuần gần nhất" in mode_filter or "1 Tháng gần nhất" in mode_filter:
        minutes_per_point = 1440  # Gộp 1 ngày = 1440 phút
    elif "Toàn bộ dữ liệu gốc" in mode_filter:
        if len(df_data) > 1 and "datetime_internal" in df_data.columns:
            try:
                time_diffs = pd.Series(df_data["datetime_internal"]).diff().dropna()
                minutes_per_point = time_diffs.dt.total_seconds().median() / 60.0
            except:
                minutes_per_point = 10
        else:
            minutes_per_point = 10
    else:
        minutes_per_point = 10

    # Đếm số điểm nằm ngoài ngưỡng
    dry_points = int((df_data["VPD (kPa)"] > vpd_max).sum())
    wet_points = int((df_data["VPD (kPa)"] < vpd_min).sum())
    
    # Quy đổi ra tổng số giờ thực tế bị áp lực sinh học
    dry_hours = round((dry_points * minutes_per_point) / 60.0, 1)
    wet_hours = round((wet_points * minutes_per_point) / 60.0, 1)
    
    return {
        "dry_hours": dry_hours,
        "wet_hours": wet_hours,
        "total_points": len(df_data)
    }


def analyze_day_by_blocks_rt(history_list, vpd_min, vpd_max, target_day_str):
    """
    Phân tích tổng hợp dữ liệu Realtime theo các buổi sinh học trong ngày.
    """
    if not history_list:
        return pd.DataFrame()
        
    df = pd.DataFrame(history_list)
    df_filtered = df[df["Ngày"] == target_day_str].copy()
    if df_filtered.empty:
        return pd.DataFrame()
        
    df_filtered["Hour"] = df_filtered["datetime_internal"].dt.hour
    
    def assign_block(h):
        if 5 <= h < 10: return "🌅 Sáng (05h - 10h)"
        elif 10 <= h < 15: return "☀️ Trưa (10h - 15h)"
        elif 15 <= h < 19: return "🌇 Chiều (15h - 19h)"
        elif 19 <= h < 23: return "🌌 Tối (19h - 23h)"
        else: return "🌙 Khuya (23h - 05h)"
        
    df_filtered["Buổi"] = df_filtered["Hour"].apply(assign_block)
    
    summary = df_filtered.groupby("Buổi").agg({
        "Nhiệt độ (°C)": "mean", "Độ ẩm (%)": "mean", "VPD (kPa)": "mean"
    }).reindex(["🌅 Sáng (05h - 10h)", "☀️ Trưa (10h - 15h)", "🌇 Chiều (15h - 19h)", "🌌 Tối (19h - 23h)", "🌙 Khuya (23h - 05h)"]).dropna()
    
    report_data = []
    for idx, row in summary.iterrows():
        avg_t = round(row["Nhiệt độ (°C)"], 1)
        avg_h = round(row["Độ ẩm (%)"], 1)
        avg_v = round(row["VPD (kPa)"], 2)
        
        if avg_v < vpd_min:
            status = "⚠️ Quá ẩm"
            solution = "Bật quạt đối lưu khí, ngừng hệ thống tưới sương."
        elif avg_v > vpd_max:
            status = "🚨 Quá khô"
            solution = "Kéo lưới cắt nắng sương, kích hoạt béc phun mịn."
        else:
            status = "✅ Lý tưởng"
            solution = "Duy trì chế độ thông gió và kiểm soát tốt hiện tại."
            
        report_data.append({
            "Khoảng Buổi": idx, "Nhiệt độ TB": f"{avg_t} °C", "Độ ẩm TB": f"{avg_h} %",
            "VPD Trung Bình": f"{avg_v} kPa", "Đánh giá sinh học": status, "Giải pháp kỹ thuật": solution
        })
        
    return pd.DataFrame(report_data)
