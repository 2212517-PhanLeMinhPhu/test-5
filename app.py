import streamlit as st
import pandas as pd
import numpy as np
import paho.mqtt.client as mqtt
import requests
import json
import random  
import plotly.express as px  # Thêm thư viện vẽ biểu đồ tương tác
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

# --- KHỔI TẠO STATE ---
if "mqtt_df" not in st.session_state:
    st.session_state.mqtt_df = pd.DataFrame()

# Trạng thái hoạt động của bộ giả lập (Mặc định là chạy tự động)
if "is_running" not in st.session_state:
    st.session_state.is_running = True

# Biến lưu vết trạm nào sẽ gửi ở giây thứ mấy
if "current_station_index" not in st.session_state:
    st.session_state.current_station_index = 0

# Biến dùng để kiểm tra nhịp tránh lặp dữ liệu khi tương tác giao diện
if "last_processed_idx" not in st.session_state:
    st.session_state.last_processed_idx = -1

# Lưu trữ link Discord Webhook trong bộ nhớ tạm
if "discord_webhook_url" not in st.session_state:
    st.session_state.discord_webhook_url = ""

# Danh sách 5 trạm trong hệ thống vườn
STATIONS_LIST = ["1", "2", "3", "4", "5"]

# =====================================================================
# BỘ TỰ ĐỘNG LÀM MỚI (XUNG NHỊP CHUẨN 30 GIÂY)
# =====================================================================
if st.session_state.is_running:
    st_autorefresh(interval=30000, key="iot_refresh")

# =====================================================================
# BỘ ĐIỀU KHIỂN BẮT ĐẦU / DỪNG LẠI (PLAY / PAUSE BUTTONS)
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
    st.warning("⏸️ Hệ thống đang: **TẠM DỪNG QUÉT** (Đang giữ nguyên thông số hiển thị và CHẶN tin nhắn)")

# =====================================================================
# CẤU HÌNH THANH TRƯỢT NGƯỠNG ĐỘNG & ĐƯỜNG DẪN DISCORD
# =====================================================================
st.subheader("⚙️ Cài Đặt Hệ Thống")

# 1. Nhập link Discord Webhook trực tiếp từ UI
input_url = st.text_input(
    "🔗 Link Discord Webhook nhận thông báo:",
    value=st.session_state.discord_webhook_url,
    placeholder="Dán link https://discord.com/api/webhooks/... vào đây",
    type="password", 
    help="Truy cập cài đặt kênh Discord -> Integrations -> Webhooks để lấy link này."
)
st.session_state.discord_webhook_url = input_url

if st.session_state.discord_webhook_url:
    st.caption("✅ Đã ghi nhận Link Discord Webhook (Đang chạy ngầm).")
else:
    st.caption("⚠️ Chưa cấu hình nhận thông báo. Hệ thống chỉ hiển thị dữ liệu trên Webboard này.")

# 2. Các thanh trượt ngưỡng VPD
low_threshold = st.slider("1. Ngưỡng VPD Thấp (Quá ẩm):", min_value=0.1, max_value=1.0, value=0.45, step=0.05, format="%.2f kPa")
high_threshold = st.slider("2. Ngưỡng VPD Cao (Khô nóng):", min_value=1.0, max_value=3.0, value=1.70, step=0.05, format="%.2f kPa")

st.session_state.low_threshold = low_threshold
st.session_state.high_threshold = high_threshold

# =====================================================================
# LOGIC TOÁN HỌC VÀ ĐÁNH GIÁ TRẠNG THÁI
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
        return "🔌 Mất tín hiệu thiết bị", f"Trạm {sid} báo độ ẩm bằng 0%.", "Kiểm tra lại dây nguồn, giắc nối đầu dò."
    
    if vpd > high_t and temp > 40.0 and humi < 40.0:
        return "🔥 BÁO ĐỘNG: KHÔ NÓNG GẮT", f"Trạm {sid} vượt ngưỡng khô gắt cài đặt ({vpd} kPa).", "CHẠY RA KÉO LƯỚI LAN ĐEN CẤT NẮNG, BẬT PHUN SƯƠNG BÙ ẨM KHẨN CẤP!"
        
    if humi >= 99.5 or vpd == 0:
        return "⚠️ THÔNG BÁO: BÃO HÒA ẨM", f"Trạm {sid} báo độ ẩm chạm trần {humi}%.", "Bật ngay quạt hút đuổi ẩm và ngừng tưới nước ngay!"

    if vpd < low_t:
        return "❌ Nhà kính quá ẩm", f"VPD thấp hơn mốc cài đặt ({vpd} < {low_t} kPa).", "Bật quạt đối lưu mạnh, mở rộng cửa hông để thoát hơi ẩm."
        
    elif vpd > high_t:
        if humi < 40.0:
            return "❌ Môi trường khô hanh", f"VPD vượt ngưỡng cao ({vpd} kPa) do thiếu ẩm.", "Bật hệ thống phun sương giữa vườn để bù lại độ ẩm."
        else:
            return "❌ Nhiệt độ tăng cao", f"Nhiệt độ nhà màng hầm nóng ({temp}°C) làm đẩy VPD lên {vpd} kPa.", "Tăng thời gian tưới nhỏ giọt dưới gốc cấp nước cho rễ."

    elif low_t <= vpd < (low_t + 0.1):
        return "⚠️ CẢNH BÁO SỚM: SẮP QUÁ ẨM", f"VPD tiến sát mốc dưới ({vpd} kPa). Độ ẩm đang tăng nhanh.", "Nên tăng nhẹ nhiệt độ phòng hoặc bật quạt đối lưu để kéo VPD lên."
        
    elif (high_t - 0.1) <= vpd <= high_t:
        return "⚠️ CẢNH BÁO SỚM: SẮP KHÔ NÓNG", f"VPD tiến sát mốc trên ({vpd} kPa). Môi trường đang khô dần.", "Nên tăng độ ẩm (phun sương nhẹ) hoặc kéo lưới lan giảm nhiệt độ phòng."

    else:
        return "Môi trường hoàn hảo lý tưởng", f"VPD đạt điểm vàng quang hợp ({vpd} kPa).", "Thời điểm vàng để cây sinh trưởng tốt. Giữ nguyên chế độ vườn."

def process_incoming_data(df_new):
    if df_new.empty:
        return

    if "is_running" in st.session_state and not st.session_state.is_running:
        return

    low_t = st.session_state.low_threshold
    high_t = st.session_state.high_threshold

    time_col = 'Thời gian' if 'Thời gian' in df_new.columns else 'time'
    stt_col = 'STT' if 'STT' in df_new.columns else 'station'

    df_normalized = df_new.copy()
    if 'time' in df_normalized.columns: df_normalized.rename(columns={'time': 'Thời gian'}, inplace=True)
    if 'station' in df_normalized.columns: df_normalized.rename(columns={'station': 'STT'}, inplace=True)
    if 'tempKK' in df_normalized.columns: df_normalized.rename(columns={'tempKK': 'Nhiệt độ'}, inplace=True)
    if 'humiKK' in df_normalized.columns: df_normalized.rename(columns={'humiKK': 'Độ ẩm'}, inplace=True)
    if 'Nhiệt Độ' in df_normalized.columns: df_normalized.rename(columns={'Nhiệt Độ': 'Nhiệt độ'}, inplace=True)

    # Đồng bộ ép kiểu dữ liệu sạch cho DataFrame lịch sử
    df_normalized['STT'] = df_normalized['STT'].astype(str)
    df_normalized['Nhiệt độ'] = pd.to_numeric(df_normalized['Nhiệt độ'])
    df_normalized['Độ ẩm'] = pd.to_numeric(df_normalized['Độ ẩm'])

    # Chuẩn hóa chia 10 cho các trạm thu phát số nguyên thô
    def scale_value(row, col_name):
        val = row[col_name]
        if row['STT'] != "5" and val > 100:
            return val / 10.0
        return val

    df_normalized['Nhiệt độ'] = df_normalized.apply(lambda r: scale_value(r, 'Nhiệt độ'), axis=1)
    df_normalized['Độ ẩm'] = df_normalized.apply(lambda r: scale_value(r, 'Độ ẩm'), axis=1)
    
    # Tính toán luôn cột giá trị VPD đưa vào lưu trữ lịch sử để vẽ biểu đồ
    df_normalized['VPD'] = df_normalized.apply(lambda r: round(calculate_vpd(r['Nhiệt độ'], r['Độ ẩm']), 3), axis=1)

    for _, row in df_normalized.iterrows():
        station_id = row['STT']
        t_val = row['Nhiệt độ']
        h_val = row['Độ ẩm']
        vpd_val = row['VPD']
        time_log = str(row['Thời gian'])
        
        status, reason, action = evaluate_status(vpd_val, t_val, h_val, station_id, low_t, high_t)
        
        msg = (
            f"📡 **[MÔ PHỎNG REALTIME] TRẠM {station_id}/5**\n"
            f"⏱ Cập nhật: `{time_log}`\n"
            f"🌡 Nhiệt độ: {t_val}°C | 💧 Độ ẩm: {h_val}%\n"
            f"💨 Chỉ số VPD: **{vpd_val} kPa**\n"
            f"📢 Trạng thái: **{status}**\n"
            f"🛠 Hướng xử lý: *{action}*"
        )
        send_discord_auto(msg)

    if st.session_state.mqtt_df.empty:
        st.session_state.mqtt_df = df_normalized
    else:
        st.session_state.mqtt_df = pd.concat([st.session_state.mqtt_df, df_normalized], ignore_index=True).drop_duplicates(subset=['STT', 'Thời gian']).tail(200)

# --- CƠ CHẾ LẮNG NGHE MQTT ---
def on_message(client, userdata, message):
    try:
        payload_str = message.payload.decode("utf-8")
        new_data = json.loads(payload_str)
        df_new = pd.DataFrame(new_data)
        process_incoming_data(df_new)
    except:
        pass

@st.cache_resource
def start_mqtt_client():
    mqtt_client = mqtt.Client()
    mqtt_client.on_message = on_message
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.subscribe(MQTT_TOPIC)
    mqtt_client.loop_start()
    return mqtt_client

_ = start_mqtt_client()

# =====================================================================
# XỬ LÝ ĐIỀU PHỐI XUNG NHỊP CHUẨN THEO TICK AUTOREFRESH
# =====================================================================
st.subheader("⏱️ Tiến Độ Điều Phối Xung Nhịp")

idx = st.session_state.current_station_index
active_station = STATIONS_LIST[idx]
next_station = STATIONS_LIST[(idx + 1) % len(STATIONS_LIST)]

col1, col2 = st.columns(2)
with col1:
    st.metric(label="🟢 Trạm vừa xử lý dữ liệu", value=f"Trạm {active_station}")
with col2:
    st.metric(label="⏳ Trạm xếp hàng kế tiếp", value=f"Trạm {next_station}")

if st.session_state.is_running and st.session_state.last_processed_idx != idx:
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if active_station == "1":
        st.session_state.mqtt_df = pd.DataFrame()

    scenarios = ["NORMAL", "MAX_HUMIDITY", "EXTREME_HOT", "LOST_SIGNAL"]
    weights = [0.85, 0.07, 0.05, 0.03]
    scenario = random.choices(scenarios, weights=weights, k=1)[0]
    
    if scenario == "NORMAL":
        temp = round(random.uniform(26.5, 35.5), 1)
        humi = round(random.uniform(55
