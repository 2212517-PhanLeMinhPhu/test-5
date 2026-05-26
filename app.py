import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta
import sys
import os
import altair as alt

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
except ModuleNotFoundError as e:
    st.error(f"❌ Không tìm thấy module bổ trợ: {e.name}. Vui lòng kiểm tra lại các file Python đi kèm.")
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

# Nhúng CSS tối ưu giao diện
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

# --- HÀM VẼ BIỂU ĐỒ ---
def get_vpd_chart(df, v_min, v_max):
    if df.empty:
        return alt.Chart(pd.DataFrame({'Trống': []})).mark_text()
    
    plot_df = df.copy()
    plot_df['Thời gian'] = pd.to_datetime(plot_df['datetime_internal'])
    
    min_y = max(0, float(plot_df['VPD (kPa)'].min()) - 0.3)
    max_y = max(v_max + 0.5, float(plot_df['VPD (kPa)'].max()) + 0.3)
    
    base = alt.Chart(plot_df).encode(
        x=alt.X('Thời gian:T', title='Thời gian', axis=alt.Axis(format='%H:%M', grid=False, tickCount=10))
    )
    
    line = base.mark_line(color='#2E7D32', strokeWidth=3).encode(
        y=alt.Y('VPD (kPa):Q', scale=alt.Scale(domain=[min_y, max_y]), title='VPD (kPa)')
    )
    
    points = base.mark_circle(size=60, color='#2E7D32').encode(
        y=alt.Y('VPD (kPa):Q'),
        tooltip=[
            alt.Tooltip('Hiển thị Giờ:N', title='Giờ'),
            alt.Tooltip('VPD (kPa):Q', title='Mức VPD')
        ]
    )
    
    rule_max = alt.Chart(pd.DataFrame({'y': [v_max]})).mark_rule(color='#FF4B4B', strokeDash=[5, 5], strokeWidth=2).encode(y='y:Q')
    rule_min = alt.Chart(pd.DataFrame({'y': [v_min]})).mark_rule(color='#0068C9', strokeDash=[5, 5], strokeWidth=2).encode(y='y:Q')
    
    band = alt.Chart(pd.DataFrame({'min': [v_min], 'max': [v_max]})).mark_rect(opacity=0.1, color='#2E7D32').encode(
        y='min:Q', y2='max:Q'
    )
    
    return (band + rule_min + rule_max + line + points).properties(height=350).interactive()

def get_weather_chart(df):
    if df.empty:
        return alt.Chart(pd.DataFrame({'Trống': []})).mark_text()
        
    plot_df = df.copy()
    plot_df['Thời gian'] = pd.to_datetime(plot_df['datetime_internal'])
    
    base = alt.Chart(plot_df).encode(
        x=alt.X('Thời gian:T', title='Thời gian', axis=alt.Axis(format='%H:%M', grid=False, tickCount=10))
    )
    
    temp_line = base.mark_line(color='#FF4B4B', strokeWidth=2).encode(
        y=alt.Y('Nhiệt độ (°C):Q', title='Nhiệt độ (°C)', scale=alt.Scale(zero=False))
    )
    
    humi_line = base.mark_line(color='#0068C9', strokeWidth=2).encode(
        y=alt.Y('Độ ẩm (%):Q', title='Độ ẩm (%)', scale=alt.Scale(zero=False))
    )
    
    return alt.layer(temp_line, humi_line).resolve_scale(y='independent').properties(height=350).interactive()

# --- HÀM BỔ TRỢ ---
def style_status_rows(row):
    styles = [''] * len(row)
    if 'Trạng thái' in row.index:
