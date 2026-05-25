import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta

# Import các module nội bộ từ kho hệ thống
from calculations import calculate_vpd, get_weather_by_time
from services import send_telegram_message, get_quick_solution
from analytics import analyze_day_by_blocks_rt, predict_vpd_trend_v3, calculate_plant_stress_hours
from charts import draw_temperature_chart, draw_humidity_chart, draw_vpd_chart, draw_combined_chart

TELE_TOKEN = "8917951413:AAE6LKUEfYEYiQrFWGoKsQn0tumZc_XbcHg"
TELE_CHAT_ID = "7290661009"

st.set_page_config(page_title="VPD Farm Analytics", page_icon="🌿", layout="wide")

# CẤU HÌNH GIAO DIỆN CHUYÊN NGHIỆP CAO
st.markdown("""
    <style>
    html, body, [data-testid="stAppViewContainer"] {
        overflow-y: auto !important;
        scroll-behavior: smooth;
    }
    .block-container { padding-top: 2rem; padding-bottom: 4rem; padding-left: 1.5rem; padding-right: 1.5rem; }
    h3 { margin-top: 0.2rem; margin-bottom: 0.8rem; padding-top: 0.2rem; }
    div[st-delegate="element-container"] { margin-bottom: 0.3rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    .stTabs [data-baseweb="tab"] { height: 45px; font-weight: bold; font-size: 16px; }
    .danger-box-red { padding: 12px; background-color: #FFEBEE; border-left: 6px solid #FF1744; color: #B71C1C; font-weight: bold; font-size: 15px; border-radius: 4px; margin-bottom: 8px; }
    .danger-box-blue { padding: 12px; background-color: #E3F2FD; border-left: 6px solid #2979FF; color: #0D47A1; font-weight: bold; font-size: 15px; border-radius: 4px; margin-bottom: 8px; }
    
    /* CSS cho phần tải file */
    .upload-header { font-size: 16px; font-weight: bold; color: #1A5276; border-bottom: 2px solid #D4E6F1; padding-bottom: 5px; margin-bottom: 12px; }
    .metric-card-upload { background-color: #F4F6F7; border: 1px solid #E5E7E9; padding: 10px; border-radius: 6px; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

# Khởi tạo bộ nhớ tạm Session State
if 'temp' not in st.session_state: st.session_state.temp = 0.0
if 'rh' not in st.session_state: st.session_state.rh = 0.0
if 'countdown' not in st.session_state: st.session_state.countdown = 15 
if 'is_running' not in st.session_state: st.session_state.is_running = False
if 'is_completed' not in st.session_state: st.session_state.is_completed = False 
if 'history' not in st.session_state: st.session_state.history = []
if 'stt_counter' not in st.session_state: st.session_state.stt_counter = 0 
if 'plant_idx' not in st.session_state: st.session_state.plant_idx = 0
if 'vpd_range_val' not in st.session_state: st.session_state.vpd_range_val = (0.6, 1.1)
if 'simulated_time' not in st.session_state: st.session_state.simulated_time = "2026-05-24 07:00:00"

if 'file_plant_idx' not in st.session_state: st.session_state.file_plant_idx = 0
if 'file_vpd_range_val' not in st.session_state: st.session_state.file_vpd_range_val = (0.6, 1.1)

# CẤU HÌNH 9 LOẠI CÂY TRỒNG ĐÀ LẠT PHỔ BIẾN
DANH_SACH_CAY = {
    "🍓 Dâu tây Đà Lạt (Hoa / Trái)": (0.6, 1.1),
    "🍓 Dâu tây Đà Lạt (Giai đoạn ngó/cây con)": (0.4, 0.8),
    "🌹 Hoa hồng nhà kính (Đà Lạt)": (0.8, 1.3),
    "🌼 Hoa cúc / Hoa đồng tiền": (0.7, 1.2),
    "🍅 Cà chua bi / 🫑 Ớt chuông Sweet Palermo": (0.8, 1.4),
    "🥦 Súp lơ xanh / Bắp cải baby (Rau ăn lá)": (0.5, 1.0),
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
    next_day_dt = current_dt + timedelta(hours=7) if current_dt.hour == 0 and current_dt.minute == 0 else current_dt + timedelta(days=1)
    if not (current_dt.hour == 0 and current_dt.minute == 0):
        next_day_dt = next_day_dt.replace(hour=7, minute=0, second=0)
    st.session_state.simulated_time = next_day_dt.strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.is_completed = False
    st.session_state.countdown = 15

def trigger_new_data(vpd_min, vpd_max):
    current_sim_datetime = datetime.strptime(st.session_state.simulated_time, "%Y-%m-%d %H:%M:%S")
    current_date_str = current_sim_datetime.strftime("Ngày %d/%m")
    st.session_state.temp, st.session_state.rh = get_weather_by_time(current_sim_datetime)
    st.session_state.countdown = 15 
    st.session_state.stt_counter += 1
    new_vpd = calculate_vpd(st.session_state.temp, st.session_state.rh)
    
    status_text = "⚠️ Quá ẩm" if new_vpd < vpd_min else ("✅ Lý tưởng" if new_vpd <= vpd_max else "🚨 Quá khô")
    tele_status = "🟦 QUÁ ẨM" if new_vpd < vpd_min else ("🟩 LÝ TƯỞNG" if new_vpd <= vpd_max else "🟥 QUÁ KHÔ")
    
    st.session_state.history.insert(0, {
        "STT": st.session_state.stt_counter, "Ngày": current_date_str,
        "Thời gian mô phỏng": current_sim_datetime, "Hiển thị Giờ": current_sim_datetime.strftime("%H:%M"),
        "datetime_internal": current_sim_datetime,
        "Nhiệt độ (°C)": st.session_state.temp, "Độ ẩm (%)": st.session_state.rh,
        "VPD (kPa)": round(new_vpd, 2), "Trạng thái": status_text
    })
    
    if TELE_TOKEN and TELE_CHAT_ID:
        sol = get_quick_solution(new_vpd, vpd_min, vpd_max, current_sim_datetime.hour)
        unique_days = sorted(list(set([r["Ngày"] for r in st.session_state.history])), reverse=True)
        history_of_latest_day = [r for r in st.session_state.history if r["Ngày"] == (unique_days[0] if unique_days else current_date_str)]
        trend, trend_type = predict_vpd_trend_v3(history_of_latest_day, current_sim_datetime.hour, vpd_min, vpd_max)
        
        prefix = "🚨 [CẢNH BÁO SỚM] " if "CẢNH BÁO SỚM" in trend else ""
        telegram_msg = (
            f"🌿 *HỆ THỐNG VPD ĐÀ LẠT REALTIME*\n⏰ {current_date_str} - {current_sim_datetime.strftime('%H:%M')}\n"
            f"📊 Môi trường: {st.session_state.temp}°C | {st.session_state.rh}%\n\n"
            f"*1️⃣ Hiện trạng:* *{new_vpd:.2f} kPa* — {tele_status}\n"
            f"*2️⃣ Biện pháp:* _{sol}_\n"
            f"*3️⃣ Dự báo:* {prefix}_{trend}_"
        )
        send_telegram_message(TELE_TOKEN, TELE_CHAT_ID, telegram_msg)
    
    next_sim_datetime = current_sim_datetime + timedelta(minutes=10)
    if next_sim_datetime.hour == 0 and next_sim_datetime.minute == 0:
        st.session_state.is_running = False     
        st.session_state.is_completed = True   
    st.session_state.simulated_time = next_sim_datetime.strftime("%Y-%m-%d %H:%M:%S")

tab_future, tab_past = st.tabs(["🔮 XEM DỰ BÁO & THEO DÕI TƯƠNG LAI", "📁 TẢI FILE & PHÂN TÍCH LỊCH SỬ"])

# --------------------------------------------------------
# TAB 1: REALTIME MONITORING
# --------------------------------------------------------
with tab_future:
    left_col, right_col = st.columns([3.5, 6.5])
    with left_col:
        st.markdown("<h3 style='color: #2E7D32; font-size: 18px;'>🤖 TRẠM ĐIỀU HÀNH THÔNG MINH</h3>", unsafe_allow_html=True)
        with st.container(border=True):
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("▶️ Bắt đầu", type="primary", use_container_width=True, key="btn_start", disabled=st.session_state.is_running):
                    if st.session_state.is_completed: setup_next_day()
                    st.session_state.is_running = True
                    if st.session_state.stt_counter == 0: trigger_new_data(st.session_state.vpd_range_val[0], st.session_state.vpd_range_val[1])
                    st.rerun()
            with col_btn2:
                if st.button("⏸️ Tạm dừng", type="secondary", use_container_width=True, key="btn_stop", disabled=not st.session_state.is_running):
                    st.session_state.is_running = False
                    st.rerun()
                    
        with st.container(border=True):
            plant_option = st.selectbox("Cây trồng mô phỏng:", plant_list_keys, index=st.session_state.plant_idx, key="plant_select", disabled=st.session_state.is_running, label_visibility="collapsed")
            st.session_state.plant_idx = plant_list_keys.index(plant_option)
            
            default_range = DANH_SACH_CAY[plant_option] if plant_option != "🛠️ Tùy chỉnh thủ công ngưỡng riêng" else st.session_state.vpd_range_val
            vpd_range = st.slider("Khoảng tối ưu (kPa):", min_value=0.0, max_value=3.0, value=default_range, step=0.1, key="vpd_slider", disabled=st.session_state.is_running or (plant_option != "🛠️ Tùy chỉnh thủ công ngưỡng riêng"))
            st.session_state.vpd_range_val = vpd_range
            vpd_min, vpd_max = vpd_range

        run_interval = 1 if st.session_state.is_running else 999999

        @st.fragment(run_every=run_interval)
        def left_panel_monitor():
            if st.session_state.is_running:
                st.session_state.countdown -= 1
                if st.session_state.countdown < 0: 
                    trigger_new_data(vpd_min, vpd_max)
                    st.rerun()
                    
            if st.session_state.is_running: st.caption(f"⏳ Đổi số sau: **{st.session_state.countdown}s**")
            elif st.session_state.is_completed: st.success("🏁 Hoàn thành chu kỳ ngày!")

            current_sim_dt = datetime.strptime(st.session_state.simulated_time, "%Y-%m-%d %H:%M:%S")
            current_date_display = current_sim_dt.strftime("Ngày %d/%m")
            
            with st.container(border=True):
                st.markdown(f"⏰ **{current_date_display} — {current_sim_dt.strftime('%H:%M')}**")
                col1, col2 = st.columns(2)
                with col1: st.metric(label="🌡️ Nhiệt độ", value=f"{st.session_state.temp}°C" if st.session_state.stt_counter > 0 else "--°C")
                with col2: st.metric(label="💧 Độ ẩm", value=f"{st.session_state.rh}%" if st.session_state.stt_counter > 0 else "--%")

            vpd_result = calculate_vpd(st.session_state.temp, st.session_state.rh)
            with st.container(border=True):
                st.markdown("<p style='color:#2E7D32; font-weight:bold; margin-bottom:2px;'>🎯 TRUNG TÂM ĐIỀU HÀNH LỆNH</p>", unsafe_allow_html=True)
                if st.session_state.stt_counter == 0:
                    st.info("Đang chờ kích hoạt trạm...")
                else:
                    status_lbl = "🟦 QUÁ ẨM" if vpd_result < vpd_min else ("🟩 LÝ TƯỞNG" if vpd_result <= vpd_max else "🟥 QUÁ KHÔ")
                    text_color = "#0068C9" if vpd_result < vpd_min else ("#2E7D32" if vpd_result <= vpd_max else "#FF4B4B")
                    
                    unique_days = sorted(list(set([r["Ngày"] for r in st.session_state.history])), reverse=True)
                    history_of_latest_day = [r for r in st.session_state.history if r["Ngày"] == (unique_days[0] if unique_days else current_date_display)]
                    
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
            with filter_col1: selected_view_day = st.selectbox("Lọc ngày lịch sử:", unique_days, label_visibility="collapsed")
            with filter_col2:
                if st.button("🗑️ Reset All", use_container_width=True, key="btn_reset_rt"):
                    st.session_state.stt_counter = 0; st.session_state.history = []; st.session_state.simulated_time = "2026-05-24 07:00:00"
                    st.session_state.is_completed = False; st.session_state.is_running = False
                    st.rerun()

            df_all_records = pd.DataFrame(st.session_state.history)
            df_filtered = df_all_records[df_all_records["Ngày"] == selected_view_day].iloc[::-1].copy()

            main_tab1, main_tab2, main_tab3 = st.tabs(["📈 Biểu đồ trực quan", "📊 Thống kê theo buổi", "📋 Bảng Nhật ký số liệu"])
            with main_tab1:
                sub_t1, sub_t2, sub_t3, sub_t4 = st.tabs(["🎯 Chỉ số VPD", "🌡️ Nhiệt độ", "💧 Độ ẩm", "📊 Tổ hợp 3 chỉ số"])
                with sub_t1: st.altair_chart(draw_vpd_chart(df_filtered, vpd_min, vpd_max), use_container_width=True)
                with sub_t2: st.altair_chart(draw_temperature_chart(df_filtered), use_container_width=True)
                with sub_t3: st.altair_chart(draw_humidity_chart(df_filtered), use_container_width=True)
                with sub_t4: st.altair_chart(draw_combined_chart(df_filtered), use_container_width=True)
            with main_tab2:
                st.dataframe(analyze_day_by_blocks_rt(st.session_state.history, vpd_min, vpd_max, selected_view_day), use_container_width=True, hide_index=True)
            with main_tab3:
                df_display = df_filtered.copy()
                df_display["Thời gian"] = df_display["Hiển thị Giờ"]
                styled_df_rt = df_display[["STT", "Thời gian", "Nhiệt độ (°C)", "Độ ẩm (%)", "VPD (kPa)", "Trạng thái"]].style.apply(style_status_rows, axis=1)
                st.dataframe(styled_df_rt, use_container_width=True, hide_index=True)


# --------------------------------------------------------
# 📁 TAB 2: UPLOAD & BULK FILE ANALYTICS (TÍCH HỢP TÍNH NĂNG CHỌN CÂY & GIỜ STRESS)
# --------------------------------------------------------
with tab_past:
    st.markdown("<h3 style='color: #1A5276; font-size: 19px;'>📁 TỰ ĐỘNG PHÂN TÍCH FILE IOT NHÀ KÍNH</h3>", unsafe_allow_html=True)
    
    top_left, top_right = st.columns([5, 5])
    
    with top_left:
        with st.container(border=True):
            st.markdown("<div class='upload-header'>🌿 1. CẤU HÌNH LOẠI CÂY TRỒNG ĐÀ LẠT</div>", unsafe_allow_html=True)
            file_plant_option = st.selectbox("Chọn mô hình cây trồng áp dụng cho file:", plant_list_keys, index=st.session_state.file_plant_idx, key="file_plant_select")
            st.session_state.file_plant_idx = plant_list_keys.index(file_plant_option)
            
            file_default_range = DANH_SACH_CAY[file_plant_option] if file_plant_option != "🛠️ Tùy chỉnh thủ công ngưỡng riêng" else st.session_state.file_vpd_range_val
            
            file_vpd_range = st.slider("Ngưỡng VPD tối ưu thiết lập (kPa):", min_value=0.0, max_value=3.0, value=file_default_range, step=0.1, key="file_vpd_slider", disabled=(file_plant_option != "🛠️ Tùy chỉnh thủ công ngưỡng riêng"))
            st.session_state.file_vpd_range_val = file_vpd_range
            file_vpd_min, file_vpd_max = file_vpd_range

    with top_right:
        with st.container(border=True):
            st.markdown("<div class='upload-header'>📥 2. TẢI DỮ LIỆU ĐẦU VÀO</div>", unsafe_allow_html=True)
            uploaded_file = st.file_uploader("Kéo thả file IoT (JSON, CSV, hoặc Excel) vào đây:", type=["json", "csv", "xlsx"], label_visibility="collapsed")
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
                df_upload = pd.DataFrame([json_data]) if isinstance(json_data, dict) and not isinstance(list(json_data.values())[0], (dict, list)) else pd.DataFrame(json_data)
            elif uploaded_file.name.endswith('.csv'):
                df_upload = pd.read_csv(uploaded_file)
            else:
                df_upload = pd.read_excel(uploaded_file)
                
            col_temp, col_rh, col_time = None, None, None
            for col in df_upload.columns:
                col_lower = str(col).lower().strip()
                if 'tempkk' in col_lower: col_temp = col
                if 'humikk' in col_lower: col_rh = col
                if any(k in col_lower for k in ['thời gian', 'time', 'gio', 'date', 'timestamp', 'mốc', 'created_at']): col_time = col

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
                except:
                    raw_datetimes.append(datetime.now())

            df_raw_calc = pd.DataFrame()
            df_raw_calc["datetime_internal"] = raw_datetimes
            
            raw_temp_series = pd.to_numeric(df_upload[col_temp], errors='coerce')
            df_raw_calc["Nhiệt độ (°C)"] = raw_temp_series.apply(lambda x: x / 10.0 if pd.notna(x) and x >= 45.0 else x)
            
            df_raw_calc["Độ ẩm (%)"] = pd.to_numeric(df_upload[col_rh], errors='coerce').apply(lambda x: x / 100.0 if pd.notna(x) and x > 100.0 else x)
            df_raw_calc = df_raw_calc[df_raw_calc["Độ ẩm (%)"] > 1.0].dropna(subset=["Nhiệt độ (°C)", "Độ ẩm (%)"]).sort_values("datetime_internal")

            if len(df_raw_calc) > 0:
                df_raw_calc["VPD_raw"] = df_raw_calc.apply(lambda row: calculate_vpd(row["Nhiệt độ (°C)"], row["Độ ẩm (%)"]), axis=1)
                df_raw_calc["only_date"] = df_raw_calc["datetime_internal"].dt.date
                available_dates = sorted(df_raw_calc["only_date"].unique())
                
                if "Tự chọn một ngày cụ thể" in time_filter_option:
                    selected_date = st.date_input("👇 Chọn ngày trích xuất dữ liệu trên lịch:", value=available_dates[-1] if available_dates else datetime.now().date())
                    df_raw_calc = df_raw_calc[df_raw_calc["only_date"] == selected_date]
                    
                elif "Từ ngày chỉ định + 29 ngày tiếp theo" in time_filter_option:
                    start_date = st.date_input("👇 Chọn ngày bắt đầu chu kỳ (Hệ thống tự động lấy thêm 29 ngày kế tiếp):", value=available_dates[0] if available_dates else datetime.now().date())
                    end_date = start_date + timedelta(days=29)
                    df_raw_calc = df_raw_calc[(df_raw_calc["only_date"] >= start_date) & (df_raw_calc["only_date"] <= end_date)]
                    
                elif "Từ ngày chỉ định + 6 ngày tiếp theo" in time_filter_option:
                    start_date = st.date_input("👇 Chọn ngày bắt đầu chu kỳ (Hệ thống tự động lấy thêm 6 ngày kế tiếp):", value=available_dates[0] if available_dates else datetime.now().date())
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
                        df_raw_calc = df_raw_calc[df_raw_calc["datetime_internal"] >= (max_time_in_file - timedelta(days=30))]

            df_for_block_analysis = df_raw_calc.copy()

            if len(df_raw_calc) > 0:
                unique_days_filtered = df_raw_calc["only_date"].nunique()
                df_resample_input = df_raw_calc[["datetime_internal", "Nhiệt độ (°C)", "Độ ẩm (%)", "VPD_raw"]].copy()
                df_resample_input.set_index("datetime_internal", inplace=True)
                
                if any(k in time_filter_option for k in ["1 Tuần gần nhất", "1 Tháng gần nhất", "tiếp theo"]):
                    df_resampled = df_resample_input.resample("1D").mean().dropna()
                elif "Xem toàn bộ dữ liệu gốc" in time_filter_option:
                    if unique_days_filtered > 2:
                        df_resampled = df_resample_input.resample("1h").mean().dropna()
                    else:
                        df_resampled = df_resample_input.resample("10min").mean().dropna()
                elif "1 Ngày gần nhất" in time_filter_option:
                    df_resampled = df_resample_input.resample("10min").mean().dropna()
                else:
                    df_resampled = df_resample_input.copy()
                
                df_resampled["datetime_internal"] = df_resampled.index
                if any(k in time_filter_option for k in ["1 Tuần gần nhất", "1 Tháng gần nhất", "tiếp theo"]) or ( "Xem toàn bộ dữ liệu gốc" in time_filter_option and unique_days_filtered > 2 ):
                    df_resampled["Hiển thị Giờ"] = df_resampled["datetime_internal"].dt.strftime("%d/%m %H:%M")
                else:
                    df_resampled["Hiển thị Giờ"] = df_resampled["datetime_internal"].dt.strftime("%H:%M")
                df_resampled.reset_index(drop=True, inplace=True)
            else:
                unique_days_filtered = 0
                df_resampled = pd.DataFrame(columns=["datetime_internal", "Nhiệt độ (°C)", "Độ ẩm (%)", "VPD_raw", "Hiển thị Giờ"])

            df_processed = pd.DataFrame()
            df_processed["datetime_internal"] = df_resampled["datetime_internal"]
            df_processed["Nhiệt độ (°C)"] = df_resampled["Nhiệt độ (°C)"].round(2)
            df_processed["Độ ẩm (%)"] = df_resampled["Độ ẩm (%)"].round(2)
            df_processed["Hiển thị Giờ"] = df_resampled["Hiển thị Giờ"]
            
            if unique_days_filtered > 2:
                df_processed["VPD (kPa)"] = df_resampled["VPD_raw"].round(2)
            else:
                df_processed["VPD (kPa)"] = df_processed.apply(lambda row: round(calculate_vpd(row["Nhiệt độ (°C)"], row["Độ ẩm (%)"]), 2), axis=1)
                
            df_processed["Ngày"] = "Dữ liệu File"
            df_processed["Trạng thái"] = df_processed["VPD (kPa)"].apply(lambda x: "⚠️ Quá ẩm" if x < file_vpd_min else ("✅ Lý tưởng" if x <= file_vpd_max else "🚨 Quá khô"))
            
            # --- KPIs THỐNG KÊ TỔNG QUAN CHU KỲ ---
            st.markdown("<div style='margin-top:15px; margin-bottom:5px; font-weight:bold; color:#1A5276;'>📊 TỔNG QUAN CHU KỲ SAU KHI GỘP SỐ LIỆU TỐI ƯU</div>", unsafe_allow_html=True)
            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            with m_col1:
                st.markdown(f"<div class='metric-card-upload'><span style='font-size:12px;color:grey;'>📈 VPD TRUNG BÌNH CHU KỲ</span><br><b style='font-size:18px;color:#2E7D32;'>{df_processed['VPD (kPa)'].mean():.2f} kPa</b></div>", unsafe_allow_html=True)
            with m_col2:
                st.markdown(f"<div class='metric-card-upload'><span style='font-size:12px;color:grey;'>🌡️ NHIỆT ĐỘ TRUNG BÌNH CHU KỲ</span><br><b style='font-size:18px;color:#FF4B4B;'>{df_processed['Nhiệt độ (°C)'].mean():.1f} °C</b></div>", unsafe_allow_html=True)
            with m_col3:
                st.markdown(f"<div class='metric-card-upload'><span style='font-size:12px;color:grey;'>💧 ĐỘ ẨM TRUNG BÌNH CHU KỲ</span><br><b style='font-size:18px;color:#0068C9;'>{df_processed['Độ ẩm (%)'].mean():.1f} %</b></div>", unsafe_allow_html=True)
            with m_col4:
                st.markdown(f"<div class='metric-card-upload'><span style='font-size:12px;color:grey;'>📋 SỐ ĐIỂM DỮ LIỆU TRÊN BIỂU ĐỒ</span><br><b style='font-size:18px;color:#5D6D7E;'>{len(df_processed)} điểm</b></div>", unsafe_allow_html=True)

            # --- TÍCH HỢP ĐÁNH GIÁ CHUYÊN SÂU: ÁP LỰC STRESS KHÍ KHỔNG CỦA CÂY ---
            stress_result = calculate_plant_stress_hours(df_processed, file_vpd_min, file_vpd_max, time_filter_option)
            st.markdown("<div style='margin-top:10px; font-weight:bold; color:#B71C1C;'>⚠️ ĐÁNH GIÁ CHUYÊN SÂU: ÁP LỰC STRESS KHÍ KHỔNG CỦA CÂY TRỒNG</div>", unsafe_allow_html=True)
            s_col1, s_col2 = st.columns(2)
            with s_col1:
                d_hrs = stress_result["dry_hours"]
                if d_hrs > 2.0:
                    st.error(f"🚨 **Stress Khô Nóng:** Cây bị đóng khí khổng do quá khô gắt suốt **{d_hrs} giờ**. Nguy cơ cháy mép lá, thui hỏng hoa non!")
                else:
                    st.success(f"✅ **Áp lực khô:** An toàn (Chỉ có {d_hrs} giờ bị khô gắt, cây chịu đựng tốt).")
            with s_col2:
                w_hrs = stress_result["wet_hours"]
                if w_hrs > 4.0:
                    st.warning(f"🟦 **Stress Ẩm Ướt:** Môi trường tích tụ ẩm cao liên tục **{w_hrs} giờ**. Rất dễ bùng phát nấm phấn trắng, sương mai tại Đà Lạt!")
                else:
                    st.success(f"✅ **Áp lực ẩm:** An toàn (Chỉ có {w_hrs} giờ đọng ẩm, lá cây nhanh khô ráo).")

            st.write("") 
            
            res_left, res_right = st.columns([6.2, 3.8])
            with res_left:
                st.markdown(f"<div style='font-weight:bold; color:#1A5276; margin-bottom:5px;'>📊 HỆ THỐNG BIỂU ĐỒ TRỰC QUAN GỌN GÀNG</div>", unsafe_allow_html=True)
                file_sub_tab1, file_sub_tab2, file_sub_tab3, file_sub_tab4 = st.tabs(["🎯 Chỉ số VPD", "🌡️ Nhiệt độ", "💧 Độ ẩm", "📊 Tổ hợp 3 chỉ số"])
                with file_sub_tab1: st.altair_chart(draw_vpd_chart(df_processed, file_vpd_min, file_vpd_max), use_container_width=True)
                with file_sub_tab2: st.altair_chart(draw_temperature_chart(df_processed), use_container_width=True)
                with file_sub_tab3: st.altair_chart(draw_humidity_chart(df_processed), use_container_width=True)
                with file_sub_tab4: st.altair_chart(draw_combined_chart(df_processed), use_container_width=True)
                
            with res_right:
                st.markdown("<div style='font-weight:bold; color:#1A5276; margin-bottom:5px;'>📋 BẢNG NHẬT KÝ THEO DÕI ĐIỂM GỘP CHU KỲ</div>", unsafe_allow_html=True)
                preview_cols = ["Hiển thị Giờ", "Nhiệt độ (°C)", "Độ ẩm (%)", "VPD (kPa)", "Trạng thái"]
                
                df_table_clean = df_processed[preview_cols].copy()
                df_table_clean["Nhiệt độ (°C)"] = df_table_clean["Nhiệt độ (°C)"].apply(lambda x: f"{float(x):.2f}")
                df_table_clean["Độ ẩm (%)"] = df_table_clean["Độ ẩm (%)"].apply(lambda x: f"{float(x):.2f}")
                df_table_clean["VPD (kPa)"] = df_table_clean["VPD (kPa)"].apply(lambda x: f"{float(x):.2f}")
                
                styled_df_file = df_table_clean.style.apply(style_status_rows, axis=1)
                st.dataframe(styled_df_file, use_container_width=True, hide_index=True, height=290)
                
                st.download_button(
                    label="📥 Xuất báo cáo tính toán chu kỳ (.csv)",
                    data=df_processed.to_csv(index=False).encode('utf-8'),
                    file_name=f"vpd_periodic_report.csv",
                    mime="text/csv",
                    use_container_width=True
                )

            st.markdown("---")
            st.markdown(f"##### 📊 BÁO CÁO PHÂN TÍCH TỔNG HỢP THEO BUỔI CHU KỲ (Dữ liệu gốc từ File)")
            
            if len(df_for_block_analysis) > 0:
                df_for_block_analysis["Hour"] = df_for_block_analysis["datetime_internal"].dt.hour
                
                def assign_block(hour):
                    if 5 <= hour < 10: return "🌅 Sáng (05h - 10h)"
                    elif 10 <= hour < 15: return "☀️ Trưa (10h - 15h)"
                    elif 15 <= hour < 19: return "🌇 Chiều (15h - 19h)"
                    elif 19 <= hour < 23: return "🌌 Tối (19h - 23h)"
                    else: return "🌙 Khuya (23h - 05h)"
                
                df_for_block_analysis["Buổi"] = df_for_block_analysis["Hour"].apply(assign_block)
                block_summary = df_for_block_analysis.groupby("Buổi").agg({
                    "Nhiệt độ (°C)": "mean", "Độ ẩm (%)": "mean", "VPD_raw": "mean"
                }).reindex(["🌅 Sáng (05h - 10h)", "☀️ Trưa (10h - 15h)", "🌇 Chiều (15h - 19h)", "🌌 Tối (19h - 23h)", "🌙 Khuya (23h - 05h)"]).dropna()
                
                block_report_rows = []
                for idx, row in block_summary.iterrows():
                    avg_t = round(row["Nhiệt độ (°C)"], 1)
                    avg_h = round(row["Độ ẩm (%)"], 1)
                    avg_v = round(row["VPD_raw"], 2)
                    
                    if avg_v < file_vpd_min:
                        conclusion = "⚠️ CHƯA ĐẠT (Quá ẩm)"
                        reason = f"Độ ẩm không khí tích tụ cao ({avg_h}%), nhiệt độ mát ẩm làm khép khí khổng."
                        solution = "Bật quạt đối lưu khí, tăng nhẹ sưởi ấm hoặc ngừng hệ thống tưới sương."
                    elif avg_v > file_vpd_max:
                        conclusion = "🚨 CHƯA ĐẠT (Quá khô)"
                        reason = f"Nhiệt độ cao ({avg_t}°C) kết hợp độ ẩm tụt sâu ({avg_h}%), bốc thoát hơi quá nhanh."
                        solution = "Kéo lưới cắt nắng sương, kích hoạt phun sương hạt mịn hoặc hệ thống tưới nhỏ giọt."
                    else:
                        conclusion = "✅ LÝ TƯỞNG"
                        reason = "Sự cân bằng tuyệt vời giữa nhiệt độ và ẩm độ, cây mở tối đa khí khổng để hấp thụ CO2 tốt nhất."
                        solution = "Giữ vững cấu hình vận hành hiện tại, kiểm tra định kỳ sensor ổn định."
                        
                    block_report_rows.append({
                        "Khoảng Buổi": idx, "Nhiệt độ TB": f"{avg_t} °C", "Độ ẩm TB": f"{avg_h} %",
                        "VPD Trung Bình": f"{avg_v} kPa", "Đánh giá": conclusion,
                        "Nguyên nhân cụ thể": reason, "Biện pháp kỹ thuật đề xuất": solution
                    })
                
                df_block_report = pd.DataFrame(block_report_rows)
                styled_df_block = df_block_report.style.apply(lambda r: [
                    'background-color: #E8F5E9; color: #1B5E20; font-weight: bold;' if "LÝ TƯỞNG" in str(r["Đánh giá"]) 
                    else ('background-color: #FFEBEE; color: #B71C1C; font-weight: bold;' if "Quá khô" in str(r["Đánh giá"]) 
                    else 'background-color: #E3F2FD; color: #0D47A1; font-weight: bold;')
                    for _ in range(len(r))
                ], axis=1)
                
                st.dataframe(styled_df_block, use_container_width=True, hide_index=True)
                
                st.write("")
                if st.button("📤 Gửi báo cáo phân tích file qua Telegram", type="primary", key="btn_send_file_tele"):
                    if TELE_TOKEN and TELE_CHAT_ID:
                        file_tele_msg = f"📂 *BÁO CÁO PHÂN TÍCH TỪ FILE IoT THÀNH CÔNG*\n"
                        file_tele_msg += f"📦 Tên file: `{uploaded_file.name}`\n"
                        file_tele_msg += f"🎯 Mô hình áp dụng: *{file_plant_option}* ({file_vpd_min}-{file_vpd_max} kPa)\n"
                        file_tele_msg += f"⏱️ Chế độ xem: _{time_filter_option}_\n"
                        file_tele_msg += f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        
                        for _, r_data in df_block_report.iterrows():
                            icon_status = "🟩" if "LÝ TƯỞNG" in r_data["Đánh giá"] else ("🟦" if "Quá ẩm" in r_data["Đánh giá"] else "🟥")
                            file_tele_msg += f"{icon_status} *{r_data['Khoảng Buổi']}*\n"
                            file_tele_msg += f"▪️ Môi trường: {r_data['Nhiệt độ TB']} | {r_data['Độ ẩm TB']}\n"
                            file_tele_msg += f"▪️ VPD TB: *{r_data['VPD Trung Bình']}*\n"
                            file_tele_msg += f"▪️ Đánh giá: _{r_data['Đánh giá']}_\n"
                            file_tele_msg += f"▪️ Giải pháp: {r_data['Biện pháp kỹ thuật đề xuất']}\n"
                            file_tele_msg += f"────────────────────\n"
                            
                        file_tele_msg += f"\n📊 _Hệ thống phân tích tự động thông minh VPD Farm_"
                        success = send_telegram_message(TELE_TOKEN, TELE_CHAT_ID, file_tele_msg)
                        if success: st.success("✅ Đã gửi toàn bộ dữ liệu báo cáo file qua Telegram thành công!")
                        else: st.error("❌ Không thể gửi tin nhắn. Vui lòng kiểm tra lại cấu hình kết nối mạng.")
            else:
                st.info("Chưa có đủ mốc thời gian thích hợp để phân tích chu kỳ buổi.")

        except Exception as err:
            st.error(f"❌ Không thể xử lý file. Chi tiết lỗi: {err}")
    else:
        st.info("💡 Hệ thống tự động bóc tách dữ liệu thông minh: Vui lòng kéo thả file dữ liệu nhà kính của bạn vào ô phía trên để bắt đầu phân tích chu kỳ chuyên sâu.")
