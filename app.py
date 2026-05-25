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
st.set_page_config(
    page_title="Hệ Thống Quét Điều Khiển", 
    page_icon="🚨", 
    layout="centered"
)

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
col_start, col_stop, col_clear = st.columns(3)

with col_start:
    if st.button("▶️ BẮT ĐẦU", use_container_width=True, type="primary"):
        st.session_state.is_running = True
        st.session_state.last_processed_idx = -1 
        st.rerun()

with col_stop:
    if st.button("⏸️ DỪNG LẠI", use_container_width=True):
        st.session_state.is_running = False
        st.rerun()

with col_clear:
    if st.button("🗑️ XÓA CACHE", use_container_width=True):
        st.session_state.mqtt_df = pd.DataFrame()
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
    placeholder="Dán link webhook vào đây",
    type="password"
)
st.session_state.discord_webhook_url = input_url

if st.session_state.discord_webhook_url:
    st.caption("✅ Đã ghi nhận Link Discord Webhook.")
else:
    st.caption("⚠️ Chưa cấu hình nhận thông báo.")

low_threshold = st.slider(
    "1. Ngưỡng VPD Thấp (Quá ẩm):", 
    min_value=0.1, max_value=1.0, value=0.45, step=0.05, format="%.2f kPa"
)
high_threshold = st.slider(
    "2. Ngưỡng VPD Cao (Khô nóng):", 
    min_value=1.0, max_value=3.0, value=1.70, step=0.05, format="%.2f kPa"
)

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
    if humi == 0:
        return ("🔌 Mất tín hiệu", f"Trạm {sid} báo độ ẩm 0%.", "Kiểm tra lại dây nguồn.")
    if vpd > high_t and temp > 40.0 and humi < 40.0:
        return ("🔥 BÁO ĐỘNG KHÔ NÓNG", f"Vượt ngưỡng khô ({vpd} kPa).", "KÉO LƯỚI LAN, PHUN SƯƠNG!")
    if humi >= 99.5 or vpd == 0:
        return ("⚠️ THÔNG BÁO BÃO HÒA", f"Độ ẩm chạm {humi}%.", "Bật quạt hút, ngừng tưới!")
    if vpd < low_t:
        return ("❌ Nhà kính quá ẩm", f"VPD thấp ({vpd} kPa).", "Bật quạt đối lưu, mở cửa.")
    elif vpd > high_t:
        if humi < 40.0:
            return ("❌ Môi trường khô hanh", f"VPD cao ({vpd} kPa).", "Bật phun sương giữa vườn.")
        else:
            return ("❌ Nhiệt độ tăng cao", f"Nhiệt độ ({temp}°C).", "Tăng tưới dưới gốc.")
    elif low_t <= vpd < (low_t + 0.1):
        return ("⚠️ CẢNH BÁO: SẮP QUÁ ẨM", f"VPD sát dưới ({vpd} kPa).", "Bật quạt đối lưu.")
    elif (high_t - 0.1) <= vpd <= high_t:
        return ("⚠️ CẢNH BÁO: SẮP KHÔ NÓNG", f"VPD sát trên ({vpd} kPa).", "Phun sương nhẹ.")
    else:
        return ("Môi trường lý tưởng", f"VPD điểm vàng ({vpd} kPa).", "Giữ nguyên chế độ.")

def process_incoming_data(df_new, silent=False):
    if df_new.empty:
        return
    if "is_running" in st.session_state and not st.session_state.is_running:
        return

    low_t = st.session_state.low_threshold
    high_t = st.session_state.high_threshold
    df_normalized = df_new.copy()

    if 'time' in df_normalized.columns:
        df_normalized.rename(columns={'time': 'Thời gian'}, inplace=True)
    if 'station' in df_normalized.columns:
        df_normalized.rename(columns={'station': 'STT'}, inplace=True)
    if 'tempKK' in df_normalized.columns:
        df_normalized.rename(columns={'tempKK': 'Nhiệt độ'}, inplace=True)
    if 'humiKK' in df_normalized.columns:
        df_normalized.rename(columns={'humiKK': 'Độ ẩm'}, inplace=True)
    if 'Nhiệt Độ' in df_normalized.columns:
        df_normalized.rename(columns={'Nhiệt Độ': 'Nhiệt độ'}, inplace=True)

    df_normalized['STT'] = df_normalized['STT'].astype(str)
    df_normalized['Nhiệt độ'] = pd.to_numeric(df_normalized['Nhiệt độ'])
    df_normalized['Độ ẩm'] = pd.to_numeric(df_normalized['Độ ẩm'])

    def scale_value(row, col_name):
        val = row[col_name]
        if row['STT'] != "5" and val > 100:
            return val / 10.0
        return val

    df_normalized['Nhiệt độ'] = df_normalized.apply(lambda r: scale_value(r, 'Nhiệt độ'), axis=1)
    df_normalized['Độ ẩm'] = df_normalized.apply(lambda r: scale_value(r, 'Độ ẩm'), axis=1)
    df_normalized['VPD'] = df_normalized.apply(lambda r: round(calculate_vpd(r['Nhiệt độ'], r['Độ ẩm']), 3), axis=1)

    if not silent:
        for _, row in df_normalized.iterrows():
            station_id = row['STT']
            t_val = row['Nhiệt độ']
            h_val = row['Độ ẩm']
            vpd_val = row['VPD']
            time_log = str(row['Thời gian'])
            status, reason, action = evaluate_status(vpd_val, t_val, h_val, station_id, low_t, high_t)
            
            msg = (
                f"📡 **[REALTIME] TRẠM {station_id}/5**\n"
                f"⏱ Cập nhật: `{time_log}`\n"
                f"🌡 Nhiệt độ: {t_val}°C | 💧 Độ ẩm: {h_val}%\n"
                f"💨 VPD: **{vpd_val} kPa**\n"
                f"📢 Trạng thái: **{status}**\n"
                f"🛠 Xử lý: *{action}*"
            )
            send_discord_auto(msg)

    if st.session_state.mqtt_df.empty:
        st.session_state.mqtt_df = df_normalized
    else:
        updated_df = pd.concat([st.session_state.mqtt_df, df_normalized], ignore_index=True)
        updated_df = updated_df.drop_duplicates(subset=['STT', 'Thời gian'])
        st.session_state.mqtt_df = updated_df.tail(500)

# =====================================================================
# KHỞI TẠO DỮ LIỆU LỊCH SỬ ĐỂ VẼ BIỂU ĐỒ NGAY LẬP TỨC
# =====================================================================
def generate_initial_history():
    records = []
    now = datetime.now()
    for i in range(12, 0, -1):
        for stt in STATIONS_LIST:
            stt_idx = int(stt) - 1
            st_time = now - timedelta(seconds=(i * 150)) + timedelta(seconds=(stt_idx * 30))
            records.append({
                "Thời gian": st_time.strftime("%H:%M:%S"),
                "STT": stt,
                "Nhiệt độ": round(random.uniform(27.0, 33.0), 1),
                "Độ ẩm": round(random.uniform(60.0, 78.0), 1)
            })
    return pd.DataFrame(records)

if st.session_state.mqtt_df.empty:
    history_df = generate_initial_history()
    process_incoming_data(history_df, silent=True)

# --- MQTT LISTENER ---
def on_message(client, userdata, message):
    try:
        payload_str = message.payload.decode("utf-8")
        new_data = json.loads(payload_str)
        df_new = pd.DataFrame(new_data)
        process_incoming_data(df_new)
    except Exception:
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
# XỬ LÝ ĐIỀU PHỐI XUNG NHỊP CHUẨN
# =====================================================================
st.subheader("⏱️ Tiến Độ Điều Phối Xung Nhịp")

idx = st.session_state.current_station_index
active_station = STATIONS_LIST[idx]
next_station = STATIONS_LIST[(idx + 1) % len(STATIONS_LIST)]

col1, col2 = st.columns(2)
with col1:
    st.metric(label="🟢 Trạm vừa xử lý", value=f"Trạm {active_station}")
with col2:
    st.metric(label="⏳ Trạm xếp hàng", value=f"Trạm {next_station}")

if st.session_state.is_running and st.session_state.last_processed_idx != idx:
    current_time_str = datetime.now().strftime("%H:%M:%S")
    scenarios = ["NORMAL", "MAX_HUMIDITY", "EXTREME_HOT", "LOST_SIGNAL"]
    weights = [0.85, 0.07, 0.05, 0.03]
    scenario = random.choices(scenarios, weights=weights, k=1)[0]
    
    if scenario == "NORMAL":
        temp = round(random.uniform(26.5, 35.5), 1)
        humi = round(random.uniform(55.0, 82.0), 1)
    elif scenario == "EXTREME_HOT":
        temp = round(random.uniform(40.5, 43.5), 1)
        humi = round(random.uniform(25.0, 38.0), 1)
    elif scenario == "MAX_HUMIDITY":
        temp = round(random.uniform(19.0, 24.0), 1)
        humi = round(random.uniform(99.5, 100.0), 1)
    elif scenario == "LOST_SIGNAL":
        temp = round(random.uniform(25.0, 32.0), 1)
        humi = 0.0

    if active_station == "5":
        mock_packet = [{"time": current_time_str, "station": "5", "tempKK": temp, "humiKK": humi}]
    else:
        mock_packet = [{"Thời gian": current_time_str, "STT": active_station, "Nhiệt độ": temp, "Độ ẩm": humi}]
        
    df_single_step = pd.DataFrame(mock_packet)
    process_incoming_data(df_single_step)
    st.session_state.last_processed_idx = idx
    st.session_state.current_station_index = (idx + 1) % len(STATIONS_LIST)

# --- COUNTDOWN UI ---
if st.session_state.is_running:
    countdown_html = """
    <div style="font-family: sans-serif; background-color: #f0f2f6; padding: 12px; border-radius: 8px; border-left: 5px solid #1f77b4; margin-bottom: 15px;">
        <span style="color: #1f77b4; font-weight: bold;">⏱️ ĐỒNG HỒ CHU KỲ QUÉT:</span> 
        <span id="countdown-timer" style="font-size: 16px; font-weight: bold; color: #ff4b4b;">30</span> giây...
    </div>
    <script>
        let timeLeft = 30;
        const timerElement = document.getElementById('countdown-timer');
        const interval = setInterval(function() {
            timeLeft--;
            if (timeLeft <= 0) { clearInterval(interval); timerElement.innerText = "0"; }
            else { timerElement.innerText = timeLeft; }
        }, 1000);
    </script>
    """
    components.html(countdown_html, height=55)
else:
    st.info("⏸️ **Bộ đếm thời gian đang dừng.**")

# =====================================================================
# BỘ VẼ BIỂU ĐỒ ĐƯỜNG THẲNG DIỄN BIẾN MƯỢT MÀ (ĐÃ FIX LỖI DẤU CHẤM)
# =====================================================================
st.subheader("📈 Biểu Đồ Diễn Biến Real-Time")
chart_df = st.session_state.mqtt_df.copy()

if not chart_df.empty and len(chart_df) > 0:
    c_metric, c_station = st.columns(2)
    with c_metric:
        select_metric = st.selectbox("📊 Chọn thông số hiển thị:", options=["Chỉ số VPD (kPa)", "Nhiệt độ (°C)", "Độ ẩm (%)"])
    with c_station:
        select_station = st.selectbox("¼ Chọn trạm xem biểu đồ:", options=["Tất cả các trạm", "Trạm 1", "Trạm 2", "Trạm 3", "Trạm 4", "Trạm 5"])
        
    metric_map = {"Chỉ số VPD (kPa)": "VPD", "Nhiệt độ (°C)": "Nhiệt độ", "Độ ẩm (%)": "Độ ẩm"}
    target_column = metric_map[select_metric]
    
    # --- THAY ĐỔI QUAN TRỌNG: CHUYỂN ĐỔI SANG TRỤC DATETIME TUYẾN TÍNH ĐỂ NỐI ĐƯỜNG THẲNG ---
    today_str = datetime.now().strftime("%Y-%m-%d")
    def to_plotly_dt(x):
        x_str = str(x).strip()
        if len(x_str) == 8 and ":" in x_str:  # Nếu là chuỗi HH:MM:SS
            return pd.to_datetime(f"{today_str} {x_str}", errors='coerce')
        return pd.to_datetime(x_str, errors='coerce')

    chart_df['Thời gian_Plotly'] = chart_df['Thời gian'].apply(to_plotly_dt)
    chart_df = chart_df.dropna(subset=['Thời gian_Plotly'])  # Loại bỏ dòng lỗi nếu có
    chart_df = chart_df.sort_values(by="Thời gian_Plotly")   # Sắp xếp đúng trình tự thời gian

    # Xử lý lọc dữ liệu dựa trên lựa chọn trạm
    if select_station == "Tất cả các trạm":
        plot_df = chart_df
        fig = px.line(
            plot_df, x="Thời gian_Plotly", y=target_column, color="STT", markers=True,
            labels={"Thời gian_Plotly": "Thời gian quét", target_column: select_metric},
            template="plotly_white", color_discrete_sequence=px.colors.qualitative.Safe
        )
        title_text = f"<b>Diễn biến {select_metric} - Toàn Bộ 5 Trạm</b>"
    else:
        station_num = select_station.replace("Trạm ", "")
        plot_df = chart_df[chart_df["STT"] == station_num].copy()
        
        fig = px.line(
            plot_df, x="Thời gian_Plotly", y=target_column, markers=True,
            labels={"Thời gian_Plotly": "Thời gian quét", target_column: select_metric}, template="plotly_white"
        )
        fig.update_traces(line_color='#1f77b4', line_width=3, marker=dict(size=8, color='#ff4b4b'))
        title_text = f"<b>Diễn biến {select_metric} - riêng Trạm {station_num}</b>"

    fig.update_layout(
        title=title_text,
        margin=dict(l=10, r=10, t=40, b=10), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig.update_xaxes(tickformat="%H:%M:%S")  # Giữ nguyên hiển thị nhãn trục X dạng Giờ:Phút:Giây gọn gàng
    fig.update_traces(line_shape='spline')   # Bo cong nét đồ thị mượt mà hơn dạng đường gãy góc
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("📊 Hệ thống đang tích lũy dữ liệu vẽ biểu đồ...")

# =====================================================================
# BẢNG TRẠNG THÁI 5 TRẠM CHU KỲ HIỆN TẠI
# =====================================================================
st.subheader("🔔 Bảng Trạng Thái 5 Trạm")
df = st.session_state.mqtt_df.copy()
rows_list = []

for s_id in STATIONS_LIST:
    s_df = pd.DataFrame()
    if not df.empty:
        s_df = df[df['STT'].astype(str) == str(s_id)]
        
    if s_df.empty:
        item = {
            "Thời gian": "Đang chờ lượt...", "Số Trạm": f"Trạm {s_id}",
            "Nhiệt độ (°C)": None, "Độ ẩm (%)": None, "VPD (kPa)": None,
            "Trạng Thái Vườn": "💤 Đang chờ quét", "Lý Do Cảm Biến": "-", "Khắc Phục": "-"
        }
        rows_list.append(item)
    else:
        last_row = s_df.sort_values(by='Thời gian').iloc[-1]
        t_v = last_row['Nhiệt độ']
        h_v = last_row['Độ ẩm']
        v_v = last_row['VPD']
        stt, rsn, act = evaluate_status(v_v, t_v, h_v, s_id, low_threshold, high_threshold)
        item = {
            "Thời gian": last_row['Thời gian'], "Số Trạm": f"Trạm {s_id}",
            "Nhiệt độ (°C)": t_v, "Độ ẩm (%)": h_v, "VPD (kPa)": v_v,
            "Trạng Thái Vườn": stt, "Lý Do Cảm Biến": rsn, "Khắc Phục": act
        }
        rows_list.append(item)

st.dataframe(pd.DataFrame(rows_list), use_container_width=True)
