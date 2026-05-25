import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta
import sys
import os

# TỰ ĐỘNG KHẮC PHỤC LỖI MODULE: Ép Python tìm kiếm module ở thư mục hiện tại
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import các module nội bộ từ kho hệ thống
try:
    from calculations import calculate_vpd, get_weather_by_time
    from services import send_telegram_message, get_quick_solution
    from analytics import analyze_day_by_blocks_rt, predict_vpd_trend_v3, calculate_plant_stress_hours
    from charts import draw_temperature_chart, draw_humidity_chart, draw_vpd_chart, draw_combined_chart
except ModuleNotFoundError as e:
    st.error(f"❌ Không tìm thấy module bổ trợ: {e.name}")
    st.info("💡 Vui lòng đảm bảo các file 'calculations.py', 'services.py', 'analytics.py', và 'charts.py' đã được upload lên cùng thư mục với file này trên GitHub.")
    st.stop()

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
    .upload-header { font-size: 16px; font-weight: bold; color: #1A5276; border-bottom: 2px solid #D4E6F1; padding-bottom: 5px; margin-bottom: 12px; }
    .metric-card-upload { background-color: #F4F6F7; border: 1px solid #E5E7E9; padding: 10px; border-radius: 6px; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

# KHỞI TẠO SESSION STATE CHUẨN AN TOÀN (Sửa triệt để lỗi gãy dòng)
CHẤU_HÌNH_MẶC_ĐỊNH = {
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
    "file_vpd_range_val": (0.6, 1.1)
}

for key, value in CHẤU_HÌNH_MẶC_ĐỊNH.items():
    if key not in st.session_state:
        st.session_state[key] = value

# CẤU HÌNH 9 LOẠI CÂY TRỒNG ĐÀ LẠT PHỔ BIẾN
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
            plant_option = st.selectbox("Cây trồng mô phỏng:", plant_list_keys, index=st.session_state.plant_idx, key="plant_select", disabled=st.session_state.is_running)
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
# 📁 TAB 2: UPLOAD & BULK FILE ANALYTICS
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
            st.
