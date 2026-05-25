import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta
import sys
import os

# Tự động tìm kiếm module ở thư mục hiện tại
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import các module nội bộ
try:
    from calculations import calculate_vpd, get_weather_by_time
    from services import send_discord_message, get_quick_solution
    from analytics import (
        analyze_day_by_blocks_rt, 
        predict_vpd_trend_v3, 
        calculate_plant_stress_hours
    )
    from charts import (
        draw_temperature_chart, 
        draw_humidity_chart, 
        draw_vpd_chart
    )
except ModuleNotFoundError as e:
    st.error(f"❌ Không tìm thấy module bổ trợ: {e.name}")
    st.info("💡 Vui lòng đảm bảo các file 'calculations.py', 'services.py', 'analytics.py', và 'charts.py' ở cùng thư mục.")
    st.stop()

st.set_page_config(page_title="VPD Farm Analytics", page_icon="🌿", layout="wide")

# CSS Giao diện
st.markdown("""
    <style>
    html, body, [data-testid="stAppViewContainer"] {
        overflow-y: auto !important;
        scroll-behavior: smooth;
    }
    .block-container { padding: 2rem 1.5rem 4rem 1.5rem; }
    h3 { margin-top: 0.2rem; margin-bottom: 0.8rem; padding-top: 0.2rem; }
    div[st-delegate="element-container"] { margin-bottom: 0.3rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    .stTabs [data-baseweb="tab"] { height: 45px; font-weight: bold; font-size: 16px; }
    .danger-box-red { padding: 12px; background-color: #FFEBEE; border-left: 6px solid #FF1744; color: #B71C1C; font-weight: bold; font-size: 15px; border-radius: 4px; margin-bottom: 8px; }
    .danger-box-blue { padding: 12px; background-color: #E3F2FD; border-left: 6px solid #2979FF; color: #0D47A1; font-weight: bold; font-size: 15px; border-radius: 4px; margin-bottom: 8px; }
    .upload-header { font-size: 16px; font-weight: bold; color: #1A5276; border-bottom: 2px solid #D4E6F1; padding-bottom: 5px; margin-bottom: 12px; }
    .metric-card-upload { background-color: #F4F6F7; border: 1px solid #E5E7E9; padding: 10px; border-radius: 6px; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

# Khởi tạo Session State
CHAU_HINH_MAC_DINH = {
    "temp": 0.0,
    "rh": 0.0,
    "countdown": 15,
    "is_running": False,
    "is_completed": False,
    "history": [],
    "stt_counter": 0,
    "plant_idx": 0,
    "vpd_range_val": (0.6, 1.1),
    "simulated_time": "2026-05-24 07:00:00",
    "file_plant_idx": 0,
    "file_vpd_range_val": (0.6, 1.1),
    "discord_webhook_input": ""
}

for key, val in CHAU_HINH_MAC_DINH.items():
    if key not in st.session_state:
        st.session_state[key] = val

DANH_SACH_CAY = {
    "🍓 Dâu tây Đà Lạt (Hoa / Trái)": (0.6, 1.1),
    "🍓 Dâu tây Đà Lạt (Giai đoạn ngó/cây con)": (0.4, 0.8),
    "🌹 Hoa hồng nhà kính (Đà Lạt)": (0.8, 1.3),
    "🌼 Hoa cúc / Hoa đồng tiền": (0.7, 1.2),
    "🍅 Cà chua bi / 🫑 Ớt chuông Sweet Palermo": (0.8, 1.4),
    "🥦 Súp lơ xanh / Bắp cabbage baby (Rau ăn lá)": (0.5, 1.0),
    "🥬 Xà lách Thủy canh (Lô lô, Romaine)": (0.4, 0.9),
    "🌱 Cây giống trong vườn ươm (Cần ẩm cao)": (0.3, 0.7),
    "🛠️ Tùy chỉnh thủ công ngưỡng riêng": (0.8, 1.2)
}
plant_list_keys = list(DANH_SACH_CAY.keys())

def style_status_rows(row):
    styles = [''] * len(row)
    status = str(row['Trạng thái'])
    if "Lý tưởng" in status:
        styles[row.index.get_loc('Trạng thái')] = 'background-color: #E8F5E9; color: #1B5E20; font-weight: bold; border-radius: 4px;'
    elif "Quá khô" in status:
        styles[row.index.get_loc('Trạng thái')] = 'background-color: #FFEBEE; color: #B71C1C; font-weight: bold; border-radius: 4px;'
    elif "Quá ẩm" in status:
        styles[row.index.get_loc('Trạng thái')] = 'background-color: #E3F2FD; color: #0D47A1; font-weight: bold; border-radius: 4px;'
    return styles

def setup_next_day():
    current_dt = datetime.strptime(st.session_state.simulated_time, "%Y-%m-%d %H:%M:%S")
    if current_dt.hour == 0 and current_dt.minute == 0:
        next_day_dt = current_dt + timedelta(hours=7)
    else:
        next_day_dt = current_dt + timedelta(days=1)
        next_day_dt = next_day_dt.replace(hour=7, minute=0, second=0)
    
    st.session_state.simulated_time = next_day_dt.strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.is_completed = False
    st.session_state.countdown = 15

def trigger_new_data(vpd_min, vpd_max):
    current_sim_dt = datetime.strptime(st.session_state.simulated_time, "%Y-%m-%d %H:%M:%S")
    current_date_str = current_sim_dt.strftime("Ngày %d/%m")
    
    st.session_state.temp, st.session_state.rh = get_weather_by_time(current_sim_dt)
    st.session_state.countdown = 15 
    st.session_state.stt_counter += 1
    new_vpd = calculate_vpd(st.session_state.temp, st.session_state.rh)
    
    if new_vpd < vpd_min:
        status_text = "⚠️ Quá ẩm"
        discord_status = "🟦 QUÁ ẨM"
    elif new_vpd <= vpd_max:
        status_text = "✅ Lý tưởng"
        discord_status = "🟩 LÝ TƯỞNG"
    else:
        status_text = "🚨 Quá khô"
        discord_status = "🟥 QUÁ KHÔ"
    
    st.session_state.history.insert(0, {
        "STT": st.session_state.stt_counter,
        "Ngày": current_date_str,
        "Thời gian mô phỏng": current_sim_dt,
        "Hiển thị Giờ": current_sim_dt.strftime("%H:%M"),
        "datetime_internal": current_sim_dt,
        "Nhiệt độ (°C)": st.session_state.temp,
        "Độ ẩm (%)": st.session_state.rh,
        "VPD (kPa)": round(new_vpd, 2),
        "Trạng thái": status_text
    })
    
    webhook_url = st.session_state.discord_webhook_input
    if webhook_url and "webhooks" in webhook_url:
        sol = get_quick_solution(new_vpd, vpd_min, vpd_max, current_sim_dt.hour)
        unique_days = sorted(list(set([r["Ngày"] for r in st.session_state.history])), reverse=True)
        latest_day = unique_days[0] if unique_days else current_date_str
        history_of_latest_day = [r for r in st.session_state.history if r["Ngày"] == latest_day]
        
        trend, trend_type = predict_vpd_trend_v3(history_of_latest_day, current_sim_dt.hour, vpd_min, vpd_max)
        prefix = "🚨 [CẢNH BÁO SỚM] " if "CẢNH BÁO SỚM" in trend else ""
        
        discord_msg = (
            f"🌿 **HỆ THỐNG VPD ĐÀ LẠT REALTIME**\n"
            f"⏰ {current_date_str} - {current_sim_dt.strftime('%H:%M')}\n"
            f"📊 Môi trường: {st.session_state.temp}°C | {st.session_state.rh}%\n\n"
            f"**1️⃣ Hiện trạng:** **{new_vpd:.2f} kPa** — {discord_status}\n"
            f"**2️⃣ Biện pháp:** *{sol}*\n"
            f"**3️⃣ Dự báo:** {prefix}*{trend}*"
        )
        send_discord_message(webhook_url, discord_msg)
    
    next_sim_dt = current_sim_dt + timedelta(minutes=10)
    if next_sim_dt.hour == 0 and next_sim_dt.minute == 0:
        st.session_state.is_running = False     
        st.session_state.is_completed = True   
    st.session_state.simulated_time = next_sim_dt.strftime("%Y-%m-%d %H:%M:%S")

tab_future, tab_past = st.tabs(["🔮 XEM DỰ BÁO & THEO DÕI TƯƠNG LAI", "📁 TẢI FILE & PHÂN TÍCH LỊCH SỬ"])

# ==========================================
# BAN ĐIỀU HÀNH REALTIME (TAB 1)
# ==========================================
with tab_future:
    left_col, right_col = st.columns([3.5, 6.5])
    with left_col:
        st.markdown("<h3 style='color: #2E7D32; font-size: 18px;'>🤖 TRẠM ĐIỀU HÀNH THÔNG MINH</h3>", unsafe_allow_html=True)
        
        with st.container(border=True):
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("▶️ Bắt đầu", type="primary", use_container_width=True, disabled=st.session_state.is_running):
                    if st.session_state.is_completed: 
                        setup_next_day()
                    st.session_state.is_running = True
                    if st.session_state.stt_counter == 0: 
                        trigger_new_data(st.session_state.vpd_range_val[0], st.session_state.vpd_range_val[1])
                    st.rerun()
            with col_btn2:
                if st.button("⏸️ Tạm dừng", type="secondary", use_container_width=True, disabled=not st.session_state.is_running):
                    st.session_state.is_running = False
                    st.rerun()
                    
        with st.container(border=True):
            plant_option = st.selectbox(
                "Cây trồng mô phỏng:", 
                plant_list_keys, 
                index=st.session_state.plant_idx, 
                disabled=st.session_state.is_running
            )
            st.session_state.plant_idx = plant_list_keys.index(plant_option)
            
            if plant_option != "🛠️ Tùy chỉnh thủ công ngưỡng riêng":
                default_range = DANH_SACH_CAY[plant_option]
            else:
                default_range = st.session_state.vpd_range_val
                
            vpd_range = st.slider(
                "Khoảng tối ưu (kPa):", 
                min_value=0.0, max_value=3.0, 
                value=default_range, step=0.1, 
                disabled=st.session_state.is_running or (plant_option != "🛠️ Tùy chỉnh thủ công ngưỡng riêng")
            )
            st.session_state.vpd_range_val = vpd_range
            vpd_min, vpd_max = vpd_range

        with st.container(border=True):
            st.session_state.discord_webhook_input = st.text_input(
                "🔗 Liên kết Discord Webhook nhận cảnh báo:",
                value=st.session_state.discord_webhook_input,
                placeholder="https://discord.com/api/webhooks/...",
                disabled=st.session_state.is_running
            )

        run_interval = 1 if st.session_state.is_running else 999999

        @st.fragment(run_every=run_interval)
        def left_panel_monitor():
            if st.session_state.is_running:
                st.session_state.countdown -= 1
                if st.session_state.countdown < 0: 
                    trigger_new_data(vpd_min, vpd_max)
                    st.rerun()
                    
            if st.session_state.is_running: 
                st.caption(f"⏳ Đổi số sau: **{st.session_state.countdown}s**")
            elif st.session_state.is_completed: 
                st.success("🏁 Hoàn thành chu kỳ ngày!")

            current_sim_dt = datetime.strptime(st.session_state.simulated_time, "%Y-%m-%d %H:%M:%S")
            current_date_display = current_sim_dt.strftime("Ngày %d/%m")
            
            with st.container(border=True):
                st.markdown(f"⏰ **{current_date_display} — {current_sim_dt.strftime('%H:%M')}**")
                col1, col2 = st.columns(2)
                with col1: 
                    st.metric(label="🌡️ Nhiệt độ", value=f"{st.session_state.temp}°C" if st.session_state.stt_counter > 0 else "--°C")
                with col2: 
                    st.metric(label="💧 Độ ẩm", value=f"{st.session_state.rh}%" if st.session_state.stt_counter > 0 else "--%")

            vpd_result = calculate_vpd(st.session_state.temp, st.session_state.rh)
            
            with st.container(border=True):
                st.markdown("<p style='color:#2E7D32; font-weight:bold; margin-bottom:2px;'>🎯 TRUNG TÂM ĐIỀU HÀNH LỆNH</p>", unsafe_allow_html=True)
                if st.session_state.stt_counter == 0:
                    st.info("Đang chờ kích hoạt trạm...")
                else:
                    if vpd_result < vpd_min:
                        status_lbl, text_color = "🟦 QUÁ ẨM", "#0068C9"
                    elif vpd_result <= vpd_max:
                        status_lbl, text_color = "🟩 LÝ TƯỞNG", "#2E7D32"
                    else:
                        status_lbl, text_color = "🟥 QUÁ KHÔ", "#FF4B4B"
                    
                    unique_days = sorted(list(set([r["Ngày"] for r in st.session_state.history])), reverse=True)
                    latest_day = unique_days[0] if unique_days else current_date_display
                    history_of_latest_day = [r for r in st.session_state.history if r["Ngày"] == latest_day]
                    
                    trend, trend_type = predict_vpd_trend_v3(history_of_latest_day, current_sim_dt.hour, vpd_min, vpd_max)
                    
                    if trend_type == "danger_red":
                        st.markdown(f"<div class='danger-box-red'>🚨 {trend}</div>", unsafe_allow_html=True)
                    elif trend_type == "danger_blue":
                        st.markdown(f"<div class='danger-box-blue'>🚨 {trend}</div>", unsafe_allow_html=True)
                    
                    st.markdown(f"**VPD Hiện Tại:** <span style='color: {text_color}; font-weight: bold; font-size:18px;'>{vpd_result:.2f} kPa</span> ({status_lbl})", unsafe_allow_html=True)
                    st.markdown(f"**Biện pháp kỹ thuật:** _{get_quick_solution(vpd_result, vpd_min, vpd_max, current_sim_dt.hour)}_")
                    if trend_type not in ["danger_red", "danger_blue"]:
                        st.markdown(f"**Dự báo chu kỳ:** {trend}")

        left_panel_monitor()

    with right_col:
        st.markdown("<h3 style='color: #2E7D32; font-size: 18px;'>📊 TRUNG TÂM PHÂN TÍCH CHU KỲ REALTIME</h3>", unsafe_allow_html=True)
        if len(st.session_state.history) == 0:
            st.info("Chưa có số liệu. Vui lòng bấm '▶️ Bắt đầu' để tải dữ liệu biểu đồ.")
        else:
            unique_days = sorted(list(set([r["Ngày"] for r in st.session_state.history])), reverse=True)
            filter_col1, filter_col2 = st.columns([7, 3])
            with filter_col1: 
                selected_view_day = st.selectbox("Lọc ngày lịch sử:", unique_days, label_visibility="collapsed")
            with filter_col2:
                if st.button("🗑️ Reset All", use_container_width=True):
                    st.session_state.stt_counter = 0
                    st.session_state.history = []
                    st.session_state.simulated_time = "2026-05-24 07:00:00"
                    st.session_state.is_completed = False
                    st.session_state.is_running = False
                    st.rerun()

            df_all_records = pd.DataFrame(st.session_state.history)
            df_filtered = df_all_records[df_all_records["Ngày"] == selected_view_day].iloc[::-1].copy()

            main_tab1, main_tab2, main_tab3 = st.tabs(["📈 Biểu đồ trực quan", "📊 Thống kê theo buổi", "📋 Bảng Nhật ký số liệu"])
            
            with main_tab1:
                # 1. Đồ thị VPD nằm cố định ở phía trên
                st.markdown("##### 🎯 Chỉ số VPD (kPa) bám biên tối ưu")
                st.altair_chart(draw_vpd_chart(df_filtered, vpd_min, vpd_max), use_container_width=True)
                
                # 2. Tạo 2 cột bên dưới để chứa Nhiệt độ và Độ ẩm song song
                sub_col1, sub_col2 = st.columns(2)
                with sub_col1:
                    st.markdown("##### 🌡️ Biến động Nhiệt độ (°C)")
                    st.altair_chart(draw_temperature_chart(df_filtered), use_container_width=True)
                with sub_col2:
                    st.markdown("##### 💧 Biến động Độ ẩm (%)")
                    st.altair_chart(draw_humidity_chart(df_filtered), use_container_width=True)
                    
            with main_tab2:
                st.dataframe(analyze_day_by_blocks_rt(st.session_state.history, vpd_min, vpd_max, selected_view_day), use_container_width=True, hide_index=True)
            
            with main_tab3:
                df_display = df_filtered.copy()
                df_display["Thời gian"] = df_display["Hiển thị Giờ"]
                styled_df_rt = df_display[["STT", "Thời gian", "Nhiệt độ (°C)", "Độ ẩm (%)", "VPD (kPa)", "Trạng thái"]].style.apply(style_status_rows, axis=1)
                st.dataframe(styled_df_rt, use_container_width=True, hide_index=True)

# ==========================================
# TAB 2: UPLOAD & BULK FILE ANALYTICS
# ==========================================
with tab_past:
    st.markdown("<h3 style='color: #1A5276; font-size: 19px;'>📁 TỰ ĐỘNG PHÂN TÍCH FILE IOT NHÀ KÍNH</h3>", unsafe_allow_html=True)
    
    top_left, top_right = st.columns([5, 5])
    
    with top_left:
        with st.container(border=True):
            st.markdown("<div class='upload-header'>🌿 1. CẤU HÌNH LOẠI CÂY TRỒNG ĐÀ LẠT</div>", unsafe_allow_html=True)
            file_plant_option = st.selectbox(
                "Chọn mô hình cây trồng áp dụng cho file:", 
                plant_list_keys, 
                index=st.session_state.file_plant_idx
            )
            st.session_state.file_plant_idx = plant_list_keys.index(file_plant_option)
            
            if file_plant_option != "🛠️ Tùy chỉnh thủ công ngưỡng riêng":
                file_default_range = DANH_SACH_CAY[file_plant_option]
            else:
                file_default_range = st.session_state.file_vpd_range_val
            
            file_vpd_range = st.slider(
                "Ngưỡng VPD tối ưu thiết lập (kPa):", 
                min_value=0.0, max_value=3.0, 
                value=file_default_range, step=0.1, 
                disabled=(file_plant_option != "🛠️ Tùy chỉnh thủ công ngưỡng riêng")
            )
            st.session_state.file_vpd_range_val = file_vpd_range
            file_vpd_min, file_vpd_max = file_vpd_range

    with top_right:
        with st.container(border=True):
            st.markdown("<div class='upload-header'>📥 2. TẢI DỮ LIỆU ĐẦU VÀO</div>", unsafe_allow_html=True)
            uploaded_file = st.file_uploader("Kéo thả file IoT vào đây:", type=["json", "csv", "xlsx"], label_visibility="collapsed")
            time_filter_option = st.selectbox(
                "📆 Chế độ lọc và gộp dữ liệu chu kỳ:",
                [
                    "📊 Xem toàn bộ dữ liệu gốc của File", 
                    "📆 Tự chọn một ngày cụ thể trên lịch", 
                    "🗓️ Chọn 1 tháng (Từ ngày chỉ định + 29 ngày tiếp theo)",
                    "📅 Chọn 1 tuần (Từ ngày chỉ định + 6 ngày tiếp theo)",
                    "⏱️ 1 Ngày gần nhất (Gom trung bình 10 phút)", 
                    "📅 1 Tuần gần nhất (Gộp trung bình 1 Ngày / 1 Điểm)", 
                    "🗓️ 1 Tháng gần nhất (Gộp trung bình 1 Ngày / 1 Điểm)"
                ]
            )
    
    if uploaded_file:
        try:
            if uploaded_file.name.endswith('.json'):
                json_data = json.load(uploaded_file)
                if isinstance(json_data, dict) and not isinstance(list(json_data.values())[0], (dict, list)):
                    df_upload = pd.DataFrame([json_data])
                else:
                    df_upload = pd.DataFrame(json_data)
            elif uploaded_file.name.endswith('.csv'):
                df_upload = pd.read_csv(uploaded_file)
            else:
                df_upload = pd.read_excel(uploaded_file)
                
            col_temp, col_rh, col_time = None, None, None
            for col in df_upload.columns:
                col_lower = str(col).lower().strip()
                if 'tempkk' in col_lower: col_temp = col
                if 'humikk' in col_lower: col_rh = col
                if any(k in col_lower for k in ['thời gian', 'time', 'gio', 'date', 'timestamp', 'mốc', 'created_at']): 
                    col_time = col

            if not col_temp:
                for col in df_upload.columns:
                    col_lower = str(col).lower().strip()
                    if any(k in col_lower for k in ['temp', 'nhiet', 't°', 'temperature']): col_temp = col
            if not col_rh:
                for col in df_upload.columns:
                    col_lower = str(col).lower().strip()
                    if any(k in col_lower for k in ['rh', 'hum', 'do am', 'humidity']): col_rh = col

            if not col_temp and len(df_upload.columns) > 0: col_temp = df_upload.columns[0]
            if not col_rh and len(df_upload.columns) > 1: col_rh = df_upload.columns[1]
            if not col_time and len(df_upload.columns) > 2: col_time = df_upload.columns[2]

            raw_datetimes = []
            for val in df_upload[col_time].astype(str):
                cleaned_val = val.strip()
                try:
                    if " " in cleaned_val and "-" in cleaned_val.split(" ")[1]:
                        date_p, time_p = cleaned_val.split(" ")
                        raw_datetimes.append(datetime.strptime(f"{date_p} {time_p.replace('-', ':')}", "%Y-%m-%d %H:%M:%S"))
                    else:
                        raw_datetimes.append(pd.to_datetime(cleaned_val))
                except Exception:
                    raw_datetimes.append(datetime.now())

            df_raw_calc = pd.DataFrame()
            df_raw_calc["datetime_internal"] = raw_datetimes
            
            raw_temp_series = pd.to_numeric(df_upload[col_temp], errors='coerce')
            df_raw_calc["Nhiệt độ (°C)"] = raw_temp_series.apply(lambda x: x / 10.0 if pd.notna(x) and x >= 45.0 else x)
            
            raw_rh_series = pd.to_numeric(df_upload[col_rh], errors='coerce')
            df_raw_calc["Độ ẩm (%)"] = raw_rh_series.apply(lambda x: x / 100.0 if pd.notna(x) and x > 100.0 else x)
            
            df_raw_calc = df_raw_calc[df_raw_calc["Độ ẩm (%)"] > 1.0].dropna(subset=["Nhiệt độ (°C)", "Độ ẩm (%)"]).sort_values("datetime_internal")

            if len(df_raw_calc) > 0:
                df_raw_calc["VPD_raw"] = df_raw_calc.apply(lambda row: calculate_vpd(row["Nhiệt độ (°C)"], row["Độ ẩm (%)"]), axis=1)
                df_raw_calc["only_date"] = df_raw_calc["datetime_internal"].dt.date
                available_dates = sorted(df_raw_calc["only_date"].unique())
                
                if "Tự chọn một ngày cụ thể" in time_filter_option:
                    selected_date = st.date_input("👇 Chọn ngày trích xuất dữ liệu trên lịch:", value=available_dates[-1] if available_dates else datetime.now().date())
                    df_raw_calc = df_raw_calc[df_raw_calc["only_date"] == selected_date]
                    
                elif "Từ ngày chỉ định + 29 ngày tiếp theo" in time_filter_option:
                    start_date = st.date_input("👇 Chọn ngày bắt đầu chu kỳ (29 ngày):", value=available_dates[0] if available_dates else datetime.now().date())
                    end_date = start_date + timedelta(days=29)
                    df_raw_calc = df_raw_calc[(df_raw_calc["only_date"] >= start_date) & (df_raw_calc["only_date"] <= end_date)]
                    
                elif "Từ ngày chỉ định + 6 ngày tiếp theo" in time_filter_option:
                    start_date = st.date_input("👇 Chọn ngày bắt đầu chu kỳ (6 ngày):", value=available_dates[0] if available_dates else datetime.now().date())
                    end_date = start_date + timedelta(days=6)
                    df_raw_calc = df_raw_calc[(df_raw_calc["only_date"] >= start_date) & (df_raw_calc["only_date"] <= end_date)]
                    
                elif "Xem toàn bộ dữ liệu gốc" in time_filter_option:
                    pass
                else:
                    max_time_in_file = df_raw_calc["datetime_internal"].max()
                    if "1 Ngày gần nhất" in time_filter_option:
                        df_raw_calc = df_raw_calc[df_raw_calc["datetime_internal"] >= (max_time_in_file - timedelta(days=1))]
                    elif "1 Tuần gần nhất" in time_filter_option:
                        df_raw_calc = df_raw_calc[df_raw_calc["datetime_internal"] >= (max_time_in_file - timedelta(days=7))]
                    elif "1 Tháng gần nhất" in time_filter_option:
                        df_raw_calc = df_raw_calc[df_raw_calc["datetime_internal"]
