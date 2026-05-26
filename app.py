import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta
import sys
import os
import altair as alt
import numpy as np
import time

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

# Nhúng CSS tối ưu giao diện gọn gàng (ĐÃ XUỐNG DÒNG AN TOÀN)
st.markdown("""
    <style>
    html, body, [data-testid="stAppViewContainer"] { 
        overflow-y: auto !important; 
        scroll-behavior: smooth; 
    }
    .block-container { 
        padding: 2rem 1.5rem 4rem 1.5rem; 
    }
    .danger-box-red { 
        padding: 12px; 
        background-color: #FFEBEE; 
        border-left: 6px solid #FF1744; 
        color: #B71C1C; 
        font-weight: bold; 
        border-radius: 4px; 
        margin-bottom: 8px; 
    }
    .danger-box-blue { 
        padding: 12px; 
        background-color: #E3F2FD; 
        border-left: 6px solid #2979FF; 
        color: #0D47A1; 
        font-weight: bold; 
        border-radius: 4px; 
        margin-bottom: 8px; 
    }
    .upload-header { 
        font-size: 16px; 
        font-weight: bold; 
        color: #1A5276; 
        border-bottom: 2px solid #D4E6F1; 
        padding-bottom: 5px; 
        margin-bottom: 12px; 
    }
    .metric-card-upload { 
        background-color: #F4F6F7; 
        border: 1px solid #E5E7E9; 
        padding: 10px; 
        border-radius: 6px; 
        text-align: center; 
    }
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
        x=alt.X(
            'Thời gian:T', 
            title='Thời gian', 
            axis=alt.Axis(format='%H:%M', grid=False, tickCount=10)
        )
    )
    line = base.mark_line(color='#2E7D32', strokeWidth=3).encode(
        y=alt.Y(
            'VPD (kPa):Q', 
            scale=alt.Scale(domain=[min_y, max_y]), 
            title='VPD (kPa)'
        )
    )
    points = base.mark_circle(size=60, color='#2E7D32').encode(
        y=alt.Y('VPD (kPa):Q'),
        tooltip=[
            alt.Tooltip('Hiển thị Giờ:N', title='Giờ'), 
            alt.Tooltip('VPD (kPa):Q', title='Mức VPD')
        ]
    )
    rule_max = alt.Chart(pd.DataFrame({'y': [v_max]})).mark_rule(
        color='#FF4B4B', strokeDash=[5, 5], strokeWidth=2
    ).encode(y='y:Q')
    
    rule_min = alt.Chart(pd.DataFrame({'y': [v_min]})).mark_rule(
        color='#0068C9', strokeDash=[5, 5], strokeWidth=2
    ).encode(y='y:Q')
    
    band = alt.Chart(pd.DataFrame({'min': [v_min], 'max': [v_max]})).mark_rect(
        opacity=0.1, color='#2E7D32'
    ).encode(y='min:Q', y2='max:Q')
    
    return (band + rule_min + rule_max + line + points).properties(height=350).interactive()

def get_weather_chart(df):
    if df.empty:
        return alt.Chart(pd.DataFrame({'Trống': []})).mark_text()
    
    plot_df = df.copy()
    plot_df['Thời gian'] = pd.to_datetime(plot_df['datetime_internal'])
    base = alt.Chart(plot_df).encode(
        x=alt.X(
            'Thời gian:T', 
            title='Thời gian', 
            axis=alt.Axis(format='%H:%M', grid=False, tickCount=10)
        )
    )
    temp_line = base.mark_line(color='#FF4B4B', strokeWidth=2).encode(
        y=alt.Y('Nhiệt độ (°C):Q', title='Nhiệt độ (°C)', scale=alt.Scale(zero=False))
    )
    humi_line = base.mark_line(color='#0068C9', strokeWidth=2).encode(
        y=alt.Y('Độ ẩm (%):Q', title='Độ ẩm (%)', scale=alt.Scale(zero=False))
    )
    
    return alt.layer(temp_line, humi_line).resolve_scale(
        y='independent'
    ).properties(height=350).interactive()

# --- HÀM BỔ TRỢ ---
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
    try:
        current_dt = datetime.strptime(st.session_state.simulated_time, "%Y-%m-%d %H:%M:%S")
        if current_dt.hour == 0 and current_dt.minute == 0: 
            next_dt = current_dt + timedelta(hours=7)
        else:
            next_dt = current_dt + timedelta(days=1)
            next_dt = next_dt.replace(hour=7, minute=0, second=0)
            
        st.session_state.simulated_time = next_dt.strftime("%Y-%m-%d %H:%M:%S")
        st.session_state.is_completed = False
        st.session_state.countdown = 15
    except Exception:
        st.session_state.simulated_time = "2026-05-24 07:00:00"

def trigger_new_data(v_min, v_max):
    try:
        cur_sim = datetime.strptime(st.session_state.simulated_time, "%Y-%m-%d %H:%M:%S")
        day_str = cur_sim.strftime("Ngày %d/%m")
        st.session_state.temp, st.session_state.rh = get_weather_by_time(cur_sim)
        st.session_state.countdown = 15 
        st.session_state.stt_counter += 1
        
        t_val = st.session_state.temp
        h_val = st.session_state.rh
        new_vpd = calculate_vpd(t_val, h_val)
        
        if new_vpd < v_min: 
            status_text, dis_status = "⚠️ Quá ẩm", "🟦 QUÁ ẨM"
        elif new_vpd <= v_max: 
            status_text, dis_status = "✅ Lý tưởng", "🟩 LÝ TƯỞNG"
        else: 
            status_text, dis_status = "🚨 Quá khô", "🟥 QUÁ KHÔ"
        
        st.session_state.history.insert(0, {
            "STT": st.session_state.stt_counter, 
            "Ngày": day_str,
            "Thời gian mô phỏng": cur_sim, 
            "Hiển thị Giờ": cur_sim.strftime("%H:%M"),
            "datetime_internal": cur_sim, 
            "Nhiệt độ (°C)": t_val, 
            "Độ ẩm (%)": h_val,
            "VPD (kPa)": round(new_vpd, 2), 
            "Trạng thái": status_text
        })
        
        MAX_HISTORY = 1000
        if len(st.session_state.history) > MAX_HISTORY:
            st.session_state.history = st.session_state.history[:MAX_HISTORY]
        
        url = st.session_state.discord_webhook_input
        if url and "webhooks" in url:
            sol = get_quick_solution(new_vpd, v_min, v_max, cur_sim.hour)
            hist_lat = [r for r in st.session_state.history if r["Ngày"] == day_str]
            trend, t_type = predict_vpd_trend_v3(hist_lat, cur_sim.hour, v_min, v_max)
            pfx = "🚨 [CẢNH BÁO SỚM] " if "CẢNH BÁO SỚM" in trend else ""
            
            msg = (
                f"🌿 **HỆ THỐNG VPD ĐÀ LẠT REALTIME**\n"
                f"⏰ {day_str} - {cur_sim.strftime('%H:%M')}\n"
                f"📊 Môi trường: {t_val}°C | {h_val}%\n\n"
                f"**1️⃣ Hiện trạng:** **{new_vpd:.2f} kPa** — {dis_status}\n"
                f"**2️⃣ Biện pháp:** *{sol}*\n"
                f"**3️⃣ Dự báo:** {pfx}*{trend}*"
            )
            send_discord_message(url, msg)
        
        nxt_sim = cur_sim + timedelta(minutes=10)
        if nxt_sim.hour == 0 and nxt_sim.minute == 0:
            st.session_state.is_running = False     
            st.session_state.is_completed = True   
        st.session_state.simulated_time = nxt_sim.strftime("%Y-%m-%d %H:%M:%S")
        
    except Exception as e:
        print(f"Error triggering data: {e}")

# --- CACHE DATA ĐỂ TỐI ƯU ---
def load_and_parse_uploaded_file(file_obj, file_name):
    if file_name.endswith('.json'):
        j_data = json.load(file_obj)
        if isinstance(j_data, dict) and not isinstance(list(j_data.values())[0], (dict, list)):
            return pd.DataFrame([j_data])
        return pd.DataFrame(j_data)
    elif file_name.endswith('.csv'): 
        return pd.read_csv(file_obj)
    return pd.read_excel(file_obj)

@st.cache_data(show_spinner="Đang đồng bộ và tính toán dữ liệu (Cache)...")
def process_data_columns(df_raw, c_time, c_temp, c_humi):
    df = pd.DataFrame()
    df["datetime_internal"] = pd.to_datetime(
        df_raw[c_time].astype(str).str.strip(), 
        errors='coerce', 
        utc=True
    ).dt.tz_localize(None)
    df["Nhiệt độ (°C)"] = pd.to_numeric(df_raw[c_temp], errors='coerce')
    df["Độ ẩm (%)"] = pd.to_numeric(df_raw[c_humi], errors='coerce')
    
    if df["Nhiệt độ (°C)"].isna().all() or df["Độ ẩm (%)"].isna().all():
        return pd.DataFrame() 
        
    df["datetime_internal"] = df["datetime_internal"].ffill().fillna(datetime.now())
    
    df.loc[df["Nhiệt độ (°C)"] >= 55.0, "Nhiệt độ (°C)"] = df["Nhiệt độ (°C)"] / 10.0
    if df["Độ ẩm (%)"].dropna().max() <= 1.05:
        df["Độ ẩm (%)"] = df["Độ ẩm (%)"] * 100.0
        
    df = df.dropna(subset=["Nhiệt độ (°C)", "Độ ẩm (%)"]).sort_values("datetime_internal")
    
    if not df.empty:
        df["VPD_raw"] = df.apply(lambda r: calculate_vpd(r["Nhiệt độ (°C)"], r["Độ ẩm (%)"]), axis=1)
        df["only_date"] = df["datetime_internal"].dt.date
    return df

# --- GIAO DIỆN CHÍNH ---
def render_sidebar_controls():
    st.markdown(
        "<h3 style='color:#2E7D32;font-size:18px;'>🤖 TRẠM ĐIỀU HÀNH</h3>", 
        unsafe_allow_html=True
    )
    
    with st.container(border=True):
        cb1, cb2 = st.columns(2)
        with cb1:
            if st.button("▶️ Bắt đầu", type="primary", use_container_width=True, disabled=st.session_state.is_running):
                if st.session_state.is_completed: 
                    setup_next_day()
                st.session_state.is_running = True
                if st.session_state.stt_counter == 0: 
                    trigger_new_data(st.session_state.vpd_range_val[0], st.session_state.vpd_range_val[1])
                st.rerun()
        with cb2:
            if st.button("⏸️ Tạm dừng", type="secondary", use_container_width=True, disabled=not st.session_state.is_running):
                st.session_state.is_running = False
                st.rerun()
                
    with st.container(border=True):
        opt = st.selectbox(
            "Cây trồng mô phỏng:", 
            plant_list_keys, 
            index=st.session_state.plant_idx, 
            disabled=st.session_state.is_running
        )
        st.session_state.plant_idx = plant_list_keys.index(opt)
        
        if opt != "🛠️ Tùy chỉnh thủ công ngưỡng riêng":
            v_range = DANH_SACH_CAY[opt]
            is_slider_disabled = True
        else:
            v_range = st.session_state.vpd_range_val
            is_slider_disabled = st.session_state.is_running
            
        vpd_sc = st.slider("Khoảng tối ưu (kPa):", 0.0, 3.0, v_range, 0.1, disabled=is_slider_disabled)
        st.session_state.vpd_range_val = vpd_sc
        
    with st.container(border=True):
        st.session_state.discord_webhook_input = st.text_input()
            "🔗 Discord Webhook URL:", 
            value=st.
