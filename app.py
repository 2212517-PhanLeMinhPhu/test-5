import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta
import sys
import os

# Tự động tìm kiếm module ở thư mục hiện tại
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import các module nội bộ với xử lý ngoại lệ
try:
    from calculations import calculate_vpd, get_weather_by_time
    from services import send_discord_message, get_quick_solution
    from analytics import (
        analyze_day_by_blocks_rt, 
        predict_vpd_trend_v3, 
        calculate_plant_stress_hours
    )
    from charts import draw_vpd_chart, draw_weather_combined_chart
except ModuleNotFoundError as e:
    st.error(f"❌ Không tìm thấy module bổ trợ: {e.name}")
    st.stop()

# --- CẤU HÌNH BAN ĐẦU ---
st.set_page_config(page_title="VPD Farm Analytics", page_icon="🌿", layout="wide")

DANH_SACH_CAY = {
    "🍓 Dâu tây Đà Lạt (Hoa / Trái)": (0.6, 1.1),
    "🍓 Dâu tây Đà Lạt (Giai đoạn ngó/cây con)": (0.4, 0.8),
    "🌹 Hoa hồng nhà kính (Đà Lạt)": (0.8, 1.3),
    "🌼 Hoa cúc / Hoa đồng tiền": (0.7, 1.2),
    "🍅 Cà chua bi / 🫑 Ớt chuông Palermo": (0.8, 1.4),
    "🥦 Súp lơ xanh / Bắp cabbage baby": (0.5, 1.0),
    "🥬 Xà lách Thủy canh (Lô lô, Romaine)": (0.4, 0.9),
    "🌱 Cây giống trong vườn ươm": (0.3, 0.7),
    "🛠️ Tùy chỉnh thủ công ngưỡng riêng": (0.8, 1.2)
}
plant_list_keys = list(DANH_SACH_CAY.keys())

# Khởi tạo Session State vững chắc
CHAU_HINH_MAC_DINH = {
    "temp": 0.0, "rh": 0.0, "countdown": 15,
    "is_running": False, "is_completed": False, "history": [],
    "stt_counter": 0, "plant_idx": 0, "vpd_range_val": (0.6, 1.1),
    "simulated_time": "2026-05-24 07:00:00", "file_plant_idx": 0,
    "file_vpd_range_val": (0.6, 1.1), "discord_webhook_input": ""
}
for key, val in CHAU_HINH_MAC_DINH.items():
    if key not in st.session_state:
        st.session_state[key] = val

# Nhúng CSS tối ưu giao diện gọn gàng
st.markdown("""
    <style>
    html, body, [data-testid="stAppViewContainer"] { overflow-y: auto !important; scroll-behavior: smooth; }
    .block-container { padding: 2rem 1.5rem 4rem 1.5rem; }
    .danger-box-red { padding: 12px; background-color: #FFEBEE; border-left: 6px solid #FF1744; color: #B71C1C; font-weight: bold; border-radius: 4px; margin-bottom: 8px; }
    .danger-box-blue { padding: 12px; background-color: #E3F2FD; border-left: 6px solid #2979FF; color: #0D47A1; font-weight: bold; border-radius: 4px; margin-bottom: 8px; }
    .upload-header { font-size: 16px; font-weight: bold; color: #1A5276; border-bottom: 2px solid #D4E6F1; padding-bottom: 5px; margin-bottom: 12px; }
    .metric-card-upload { background-color: #F4F6F7; border: 1px solid #E5E7E9; padding: 10px; border-radius: 6px; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

# --- HÀM BỔ TRỢ GIAO DIỆN ---
def style_status_rows(row):
    styles = [''] * len(row)
    if 'Trạng thái' in row.index:
        idx = row.index.get_loc('Trạng thái')
        status = str(row['Trạng thái'])
        if "Lý tưởng" in status:
            styles[idx] = 'background-color: #E8F5E9; color: #1B5E20; font-weight: bold;'
        elif "Quá khô" in status:
            styles[idx] = 'background-color: #FFEBEE; color: #B71C1C; font-weight: bold;'
        elif "Quá ẩm" in status:
            styles[idx] = 'background-color: #E3F2FD; color: #0D47A1; font-weight: bold;'
    return styles

def setup_next_day():
    current_dt = datetime.strptime(st.session_state.simulated_time, "%Y-%m-%d %H:%M:%S")
    if current_dt.hour == 0 and current_dt.minute == 0:
        next_dt = current_dt + timedelta(hours=7)
    else:
        next_dt = current_dt + timedelta(days=1)
        next_dt = next_dt.replace(hour=7, minute=0, second=0)
    st.session_state.simulated_time = next_dt.strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.is_completed = False
    st.session_state.countdown = 15

def trigger_new_data(v_min, v_max):
    cur_sim = datetime.strptime(st.session_state.simulated_time, "%Y-%m-%d %H:%M:%S")
    day_str = cur_sim.strftime("Ngày %d/%m")
    
    st.session_state.temp, st.session_state.rh = get_weather_by_time(cur_sim)
    st.session_state.countdown = 15 
    st.session_state.stt_counter += 1
    
    t_val, h_val = st.session_state.temp, st.session_state.rh
    new_vpd = calculate_vpd(t_val, h_val)
    
    if new_vpd < v_min:
        status_text, dis_status = "⚠️ Quá ẩm", "🟦 QUÁ ẨM"
    elif new_vpd <= v_max
