import streamlit as st
import pandas as pd
import numpy as np
import paho.mqtt.client as mqtt
import requests
import json
import random  
import plotly.express as px  
import streamlit.components.v1 as components
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# =====================================================================
# CẤU HÌNH GIAO DIỆN DI ĐỘNG
# =====================================================================
st.set_page_config(page_title="Hệ Thống Quét Điều Khiển", page_icon="🚨", layout="centered")

st.title("🚨 Giám Sát Real-Time Quét Vòng 5 Trạm")
st.markdown("Mô phỏng: **Mỗi trạm gửi cách nhau 150s, các trạm lệch pha nhau đúng 30s**.")

# --- CẤU HÌNH THÔNG TIN KẾT NỐI MQTT ---
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC = "vuon_thong_minh/duy_tran/sensors"

# --- KHỞI TẠO STATE ---
if "mqtt_df" not in st.session_state:
    st.session_state.mqtt_df = pd.DataFrame()

if "is_running" not in st.session_state:
    st.session_state.is_running = True

if "current_station_index" not in st.session_state:
    st.session_state.current_station_index = 0

if "last_processed_idx" not in st.session_state:
    st.session_state.last_processed_idx = -1

if "discord_webhook_url" not in st.session_state:
    st.session_state.discord_webhook_url = ""

STATIONS_LIST = ["1", "2", "3", "4", "5"]

# =====================================================================
# BỘ TỰ ĐỘNG LÀM MỚI
# =====================================================================
if st.session_state.is_running:
    st_autorefresh(interval=30000, key="iot_refresh")

# =====================================================================
# BỘ ĐIỀU KHIỂN BẮT ĐẦU / DỪNG LẠI
# =====================================================================
st.subheader("🎮 Bộ Điều Khiển Hệ Thống")
col_start, col_stop = st.columns(2)

with col_start:
    if st.button("▶️ BẮT ĐẦU (Chạy tự động)", use_container_width=True, type="primary"):
        st.session_state.is_running = True
        st.session_state.last_processed_idx = -1 
        st.rerun()

with col_stop:
    if st.button("⏸️ DỪNG LẠI (Tạm dừng quét)", use_container_width=True):
        st.session_state.is_running = False
        st.rerun()

if st.session_state.is_running:
    st.success("🤖 Hệ thống đang: **CHẠY TỰ ĐỘNG (Xung nhịp 30s chuẩn)**")
else:
    st.warning("⏸️ Hệ thống đang: **TẠM DỪNG QUÉT**")

# =====================================================================
# CẤU HÌNH HỆ THỐNG
# =====================================================================
st.subheader("⚙️ Cài Đặt Hệ Thống")

input_url = st.text_input(
    "🔗 Link Discord Webhook nhận thông báo:",
    value=st.session_state.discord_webhook_url,
    placeholder="Dán link https://discord.com/api/webhooks/... vào đây",
    type="password", 
    help="Truy cập cài đặt kênh Discord -> Integrations -> Webhooks để lấy link."
)
st.session_state.discord_webhook_url = input_url

if st.session_state.discord_webhook_url:
    st.caption("✅ Đã ghi nhận Link Discord Webhook.")
else:
    st.caption("⚠️ Chưa cấu hình nhận thông báo.")

low_threshold = st.slider("1. Ngưỡng VPD Thấp (Quá ẩm):", min_value=0.1, max_value=1.0, value=0.45, step=0.05, format="%.2f kPa")
high_threshold = st.slider("2. Ngưỡng VPD Cao (Khô nóng):", min_value=1.0, max_value=3.0, value=1.70, step=0.05, format="%.2f kPa")

st.session_state.low_threshold = low_threshold
st.session_state.high_threshold = high_threshold

# =====================================================================
# LOGIC VÀ ĐÁNH GIÁ TRẠNG THÁI
# =====================================================================
def calculate_vpd(temp, humi):
    vp_sat = 0.61078 * np.exp((17.27 * temp) / (temp + 237.3))
    return float(np.clip(vp_sat * (1 - (humi / 100)), 0, None))

def send_discord_auto(message):
    webhook_url = st.session_state.get("discord_webhook_url", "")
    if not webhook_url or "discord.com/api/webhooks" not in webhook_url:
        return
    try: 
        requests.post(webhook_url, json={"content": message}, timeout=2)
    except: 
        pass

def evaluate_status(vpd, temp, humi, station_id, low_t, high_t):
    sid = str(station_id)
    
    if humi == 0:
        return "🔌 Mất tín hiệu thiết bị", f"Trạm {sid} báo độ ẩm bằng 0%.", "Kiểm tra lại dây nguồn."
    
    if vpd > high_t and temp > 40.0 and humi < 40.0:
        return "🔥 BÁO ĐỘNG: KHÔ NÓNG GẮT", f"Vượt ngưỡng khô gắt ({vpd} kPa).", "KÉO LƯỚI LAN, BẬT PHUN SƯƠNG BÙ ẨM!"
        
    if humi >= 99.5 or vpd == 0:
        return "⚠️ THÔNG BÁO: BÃO HÒA ẨM", f"Độ ẩm chạm trần {humi}%.", "Bật quạt hút đuổi ẩm và ngừng tưới!"

    if vpd < low_t:
        return "❌ Nhà kính quá ẩm", f"VPD thấp hơn cài đặt ({vpd} < {low_t} kPa).", "Bật quạt đối lưu, mở rộng cửa hông."
        
    elif vpd > high_t:
        if humi < 40.0:
            return "❌ Môi trường khô hanh", f"VPD vượt ngưỡng ({vpd} kPa) do thiếu ẩm.", "Bật phun sương giữa vườn."
        else:
            return "❌ Nhiệt độ tăng cao", f"Nhiệt độ nóng ({temp}°C) làm VPD lên {vpd} kPa.", "Tăng thời gian tưới dưới gốc."

    elif low_t <= vpd < (low_t + 0.1):
        return "⚠️ CẢNH BÁO SỚM: SẮP QUÁ ẨM", f"VPD sát mốc dưới ({vpd} kPa).", "Bật quạt đối lưu để kéo VPD lên."
        
    elif (high_t - 0.1) <= vpd <= high_t:
        return "⚠️ CẢNH BÁO SỚM: SẮP KHÔ NÓNG", f"VPD sát mốc trên ({vpd} kPa).", "Phun sương nhẹ hoặc kéo lưới lan."

    else:
        return "Môi trường hoàn hảo lý tưởng", f"VPD đạt điểm vàng ({vpd} kPa).", "Giữ nguyên chế độ vườn."

def process_incoming_data(df_new):
    if df_new.empty:
        return

    if "is_running" in st.session_state and not st.session_state.is_running:
        return

    low_t = st.session_state.low_threshold
    high_t = st.session_state.high_threshold

    df_normalized = df_new.copy()
    if 'time' in df_normalized.columns: df_normalized.rename(columns={'time': 'Thời gian'}, inplace=True)
    if 'station' in df
