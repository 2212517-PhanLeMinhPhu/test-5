import streamlit as st
import pandas as pd
import numpy as np
import paho.mqtt.client as mqtt
import requests
import json
import random  
import plotly.express as px  
import streamlit.components.v1 as components
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh

# =====================================================================
# CẤU HÌNH GIAO DIỆN DI ĐỘNG
# =====================================================================
st.set_page_config(page_title="Hệ Thống Quét Điều Khiển", page_icon="🚨", layout="centered")

st.title("🚨 Giám Sát Real-Time Quét Vòng 5 Trạm")
st.markdown("Mô phỏng: **Mỗi trạm gửi cách nhau 150s, các trạm lệch pha nhau đúng 30s**.")

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC = "vuon_thong_minh/duy_tran/sensors"
STATIONS_LIST = ["1", "2", "3", "4", "5"]

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
st.session_state.discord_webhook_url = st.text_input(
    "🔗 Link Discord Webhook nhận thông báo:",
    value=st.session_state.discord_webhook_url, placeholder="Dán link webhook vào đây", type="password"
)
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
    if not webhook_url or "discord" not in webhook_url:
        return
    try: 
        requests.post(webhook_url, json={"content": message}, timeout=2)
    except Exception: 
        pass

def evaluate_status(vpd, temp, humi, station_id, low_t, high_t):
    sid = str(station_id)
    if humi == 0: return ("🔌 Mất tín hiệu", f"Trạm {sid} báo độ ẩm 0%.", "Kiểm tra lại dây nguồn.")
    if vpd > high_t and temp > 40.0 and humi < 40.0: return ("🔥 BÁO ĐỘNG KHÔ NÓNG", f"Vượt ngưỡng khô ({vpd} kPa).", "KÉO LƯỚI LAN, PHUN SƯƠNG!")
    if humi >= 99.5 or vpd == 0: return ("⚠️ THÔNG BÁO BÃO HÒA", f"Độ ẩm chạm {humi}%.", "Bật quạt hút, ngừng tưới!")
    if vpd < low_t: return ("❌ Nhà kính quá ẩm", f"VPD thấp ({vpd} kPa).", "Bật quạt đối lưu, mở cửa.")
    elif vpd > high_t:
        if humi < 40.0: return ("❌ Môi trường khô hanh", f"VPD cao ({vpd} kPa).", "Bật phun sương giữa vườn.")
        else: return ("❌ Nhiệt độ tăng cao", f"Nhiệt độ ({temp}°C).", "Tăng tưới dưới gốc.")
    elif low_t <= vpd < (low_t + 0.1): return ("⚠️ CẢNH BÁO: SẮP QUÁ ẨM", f"VPD sát dưới ({vpd} kPa).", "Bật quạt đối lưu.")
    elif (high_t - 0.1) <= vpd <= high_t: return ("⚠️ CẢNH BÁO: SẮP KHÔ NÓNG", f"VPD sát trên ({vpd} kPa).", "Phun sương nhẹ.")
    else: return ("Môi trường lý tưởng", f"VPD điểm vàng ({vpd} kPa).", "Giữ nguyên chế độ.")

def process_incoming_data(df_new, silent=False):
    if df_new.empty: return
    low_t = st.session_state.low_threshold
    high_t = st.session_state.high_threshold
    df_n = df_new.copy()

    if 'time' in df_n.columns: df_n.rename(columns={'time': 'Thời gian'}, inplace=True)
    if 'station' in df_n.columns: df_n.rename(columns={'station': 'STT'}, inplace=True)
    if 'tempKK' in df_n.columns: df_n.rename(columns={'tempKK': 'Nhiệt độ'}, inplace=True)
    if 'humiKK' in df_n.columns: df_n.rename(columns={'humiKK': 'Độ ẩm'}, inplace=True)

    df_n['STT'] = df_n['STT'].astype(str)
    df_n['Nhiệt độ'] = pd.to_numeric(df_n['Nhiệt độ'])
    df_n['Độ ẩm'] = pd.to_numeric(df_n['Độ ẩm'])

    def scale_value(row, col):
        val = row[col]
        return val / 10.0 if row['STT'] != "5" and val > 100 else val

    df_n['Nhiệt độ'] = df_n.apply(lambda r: scale_value(r, 'Nhiệt độ'), axis=1)
    df_n['Độ ẩm'] = df_n.apply(lambda r: scale_value(r, 'Độ ẩm'), axis=1)
    df_n['VPD'] = df_n.apply(lambda r: round(calculate_vpd(r['Nhiệt độ'], r['Độ ẩm']), 3), axis=1)

    if not silent:
        for _, row in df_n.iterrows():
            stt, t_val, h_val, vpd_val, t_log = row['STT'], row['Nhiệt độ'], row['Độ ẩm'], row['VPD'], str(row['Thời gian'])
            status, reason, action = evaluate_status(vpd_val, t_val, h_val, stt, low_t, high_t)
            msg = f"📡 **[REALTIME] TRẠM {stt}/5**\n⏱ Cập nhật: `{t_log}`\n🌡 Nhiệt độ: {t_val}°C | 💧 Độ ẩm: {h_val}%\n💨 VPD: **{vpd_val} kPa**\n📢 Trạng thái: **{status}**\n🛠 Xử lý: *{action}*"
            send_discord_auto(msg)

    if st.session_state.mqtt_df.empty:
        st.session_state.mqtt_df = df_n
    else:
        updated_df = pd.concat([st.session_state.mqtt_df, df_n], ignore_index=True)
        updated_df = updated_df.drop_duplicates(subset=['STT', 'Thời gian'])
        st.session_state.mqtt_df = updated_df.tail(1000)

# TỰ ĐỘNG TẠO DỮ LIỆU LỊCH SỬ KHI VỪA VÀO APP ĐỂ BIỂU ĐỒ CÓ ĐƯỜNG NỐI NGAY LẬP TỨC
def generate_initial_history():
    records = []
    now = datetime.now()
    for i in range(10, 0, -1):
        for stt in STATIONS_LIST:
            stt_idx = int(stt) - 1
            st_time = now - timedelta(seconds=(i * 150)) + timedelta(seconds=(stt_idx * 30))
            records.append({
                "Thời gian": st_time.strftime("%Y-%m-%d %H:%M:%S"),
                "STT": stt,
                "Nhiệt độ": round(random.uniform(28.0, 32.0), 1),
                "Độ ẩm": round(random.uniform(60.0, 75.0), 1)
            })
    return pd.DataFrame(records)

if st.session_state.mqtt_df.empty:
    hist_df = generate_initial_history()
    process_incoming_data(hist_df, silent=True)

# --- MQTT LISTENER ---
def on_message(client, userdata, message):
    try:
        new_data = json.loads(message.payload.decode("utf-8"))
        process_incoming_data(pd.DataFrame(new_data))
    except: pass

@st.cache_resource
def start_mqtt_client():
    client = mqtt.Client()
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.subscribe(MQTT_TOPIC)
    client.loop_start()
    return client
_ = start_mqtt_client()

# =====================================================================
# XỬ LÝ ĐIỀU PHỐI XUNG NHỊP CHUẨN
# =====================================================================
st.subheader("⏱️ Tiến Độ Điều Phối Xung Nhịp")
idx = st.session_state.current_station_index
active_station = STATIONS_LIST[idx]
next_station = STATIONS_LIST[(idx + 1) % len(STATIONS_LIST)]

c1, c2 = st.columns(2)
c1.metric(label="🟢 Trạm vừa xử lý", value=f"Trạm {active_station}")
c2.metric(label="⏳ Trạm xếp hàng", value=f"Trạm {next_station}")

if st.session_state.is_running and st.session_state.last_processed_idx != idx:
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scenario = random.choices(["NORMAL", "MAX_HUMIDITY", "EXTREME_HOT", "LOST_SIGNAL"], weights=[0.85, 0.07, 0.05, 0.03], k=1)[0]
    
    if scenario == "NORMAL": temp, humi = round(random.uniform(26.5, 35.5), 1), round(random.uniform(55.0, 82.0), 1)
    elif scenario == "EXTREME_HOT": temp, humi = round(random.uniform(40.5, 43.5), 1), round(random.uniform(25.0, 38.0), 1)
    elif scenario == "MAX_HUMIDITY": temp, humi = round(random.uniform(19.0, 24.0), 1), round(random.uniform(99.5, 100.0), 1)
    else: temp, humi = round(random.uniform(25.0, 32.0), 1), 0.0

    mock_packet = [{"Thời gian": current_time_str, "STT": active_station, "Nhiệt độ": temp, "Độ ẩm": humi}]
    process_incoming_data(pd.DataFrame(mock_packet))
    st.session_state.last_processed_idx = idx
    st.session_state.current_station_index = (idx + 1) % len(STATIONS_LIST)

# --- COUNTDOWN UI ---
if st.session_state.is_running:
    components.html("""
    <div style="font-family: sans-serif; background-color: #f0f2f6; padding: 12px; border-radius: 8px; border-left: 5px solid #1f77b4; margin-bottom: 15px;">
        <span style="color: #1f77b4; font-weight: bold;">⏱️ ĐỒNG HỒ CHU KỲ QUÉT:</span> <span id="cd" style="font-size: 16px; font-weight: bold; color: #ff4b4b;">30</span> giây...
    </div>
    <script>
        let t = 30; const e = document.getElementById('cd');
        const i = setInterval(() => { t--; if(t<=0){clearInterval(i); e.innerText="0";} else e.innerText=t; }, 1000);
    </script>
    """, height=55)
else:
    st.info("⏸️ **Bộ đếm thời gian đang dừng.**")

# =====================================================================
# BỘ VẼ BIỂU ĐỒ ĐƯỜNG THẲNG DIỄN BIẾN MƯỢT MÀ
# =====================================================================
st.subheader("📈 Biểu Đồ Diễn Biến Real-Time")
chart_df = st.session_state.mqtt_df.copy()

if not chart_df.empty:
    select_metric = st.selectbox("📊 Chọn thông số hiển thị:", options=["Chỉ số VPD (kPa)", "Nhiệt độ (°C)", "Độ ẩm (%)"])
    metric_map = {"Chỉ số VPD (kPa)": "VPD", "Nhiệt độ (°C)": "Nhiệt độ", "Độ ẩm (%)": "Độ ẩm"}
    target_column = metric_map[select_metric]
    
    # Ép chuẩn định dạng thời gian để thư viện nối liền đường thẳng
    chart_df['Thời gian'] = pd.to_datetime(chart_df['Thời gian'])
    
    single_station_df = chart_df[chart_df["STT"] == active_station].copy()
    single_station_df = single_station_df.sort_values(by="Thời gian")
    
    if len(single_station_df) > 1:
        fig = px.area(
            single_station_df, x="Thời gian", y=target_column, markers=True,
            labels={"Thời gian": "Giờ cập nhật", target_column: select_metric}, template="plotly_white"
        )
        fig.update_xaxes(tickformat="%H:%M:%S")
        fig.update_layout(
            title=f"<b>Diễn biến {select_metric} - Trạm {active_station}</b>",
            margin=dict(l=10, r=10, t=40, b=10), hovermode="x unified"
        )
        fig.update_traces(
            line_shape='spline', line_color='#1f77b4', line_width=3,
            marker=dict(size=8, color='#ff4b4b'), fillcolor='rgba(31, 119, 180, 0.15)'
        )
        st.plotly_chart(fig, use_container_width=True)

# =====================================================================
# BẢNG TRẠNG THÁI 5 TRẠM CHU KỲ HIỆN TẠI
# =====================================================================
st.subheader("🔔 Bảng Trạng Thái 5 Trạm")
df = st.session_state.mqtt_df.copy()
rows_list = []

for s_id in STATIONS_LIST:
    s_df = df[df['STT'].astype(str) == str(s_id)].copy()
    if s_df.empty:
        rows_list.append({
            "Thời gian": "Đang chờ lượt...", "Số Trạm": f"Trạm {s_id}", "Nhiệt độ (°C)": None, "Độ ẩm (%)": None,
            "VPD (kPa)": None, "Trạng Thái Vườn": "💤 Đang chờ quét", "Lý Do": "-", "Khắc Phục": "-"
        })
    else:
        s_df['Thời gian'] = pd.to_datetime(s_df['Thời gian'])
        last_row = s_df.sort_values(by='Thời gian').iloc[-1]
        t_v, h_v, v_v = last_row['Nhiệt độ'], last_row['Độ ẩm'], last_row['VPD']
        stt, rsn, act = evaluate_status(v_v, t_v, h_v, s_id, low_threshold, high_threshold)
        rows_list.append({
            "Thời gian": last_row['Thời gian'].strftime("%H:%M:%S"), "Số Trạm": f"Trạm {s_id}",
            "Nhiệt độ (°C)": t_v, "Độ ẩm (%)": h_v, "VPD (kPa)": v_v,
            "Trạng Thái Vườn": stt, "Lý Do": rsn, "Khắc Phục": act
        })

st.dataframe(pd.DataFrame(rows_list), use_container_width=True)
