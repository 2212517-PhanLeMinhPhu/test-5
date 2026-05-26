import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta
import sys
import os
import time
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
    if df.empty: return alt.Chart(pd.DataFrame({'Trống': []})).mark_text()
    plot_df = df.copy()
    plot_df['Thời gian'] = pd.to_datetime(plot_df['datetime_internal'])
    min_y = max(0, float(plot_df['VPD (kPa)'].min()) - 0.3)
    max_y = max(v_max + 0.5, float(plot_df['VPD (kPa)'].max()) + 0.3)
    base = alt.Chart(plot_df).encode(x=alt.X('Thời gian:T', title='Thời gian', axis=alt.Axis(format='%H:%M', grid=False, tickCount=10)))
    line = base.mark_line(color='#2E7D32', strokeWidth=3).encode(y=alt.Y('VPD (kPa):Q', scale=alt.Scale(domain=[min_y, max_y]), title='VPD (kPa)'))
    points = base.mark_circle(size=60, color='#2E7D32').encode(y=alt.Y('VPD (kPa):Q'), tooltip=[alt.Tooltip('Hiển thị Giờ:N', title='Giờ'), alt.Tooltip('VPD (kPa):Q', title='Mức VPD')])
    rule_max = alt.Chart(pd.DataFrame({'y': [v_max]})).mark_rule(color='#FF4B4B', strokeDash=[5, 5], strokeWidth=2).encode(y='y:Q')
    rule_min = alt.Chart(pd.DataFrame({'y': [v_min]})).mark_rule(color='#0068C9', strokeDash=[5, 5], strokeWidth=2).encode(y='y:Q')
    band = alt.Chart(pd.DataFrame({'min': [v_min], 'max': [v_max]})).mark_rect(opacity=0.1, color='#2E7D32').encode(y='min:Q', y2='max:Q')
    return (band + rule_min + rule_max + line + points).properties(height=350).interactive()

def get_weather_chart(df):
    if df.empty: return alt.Chart(pd.DataFrame({'Trống': []})).mark_text()
    plot_df = df.copy()
    plot_df['Thời gian'] = pd.to_datetime(plot_df['datetime_internal'])
    base = alt.Chart(plot_df).encode(x=alt.X('Thời gian:T', title='Thời gian', axis=alt.Axis(format='%H:%M', grid=False, tickCount=10)))
    temp_line = base.mark_line(color='#FF4B4B', strokeWidth=2).encode(y=alt.Y('Nhiệt độ (°C):Q', title='Nhiệt độ (°C)', scale=alt.Scale(zero=False)))
    humi_line = base.mark_line(color='#0068C9', strokeWidth=2).encode(y=alt.Y('Độ ẩm (%):Q', title='Độ ẩm (%)', scale=alt.Scale(zero=False)))
    return alt.layer(temp_line, humi_line).resolve_scale(y='independent').properties(height=350).interactive()

# --- HÀM BỔ TRỢ ---
def style_status_rows(row):
    styles = [''] * len(row)
    if 'Trạng thái' in row.index:
        idx = row.index.get_loc('Trạng thái')
        status = str(row['Trạng thái'])
        if "Lý tưởng" in status: styles[idx] = 'background-color: #E8F5E9; color: #1B5E20; font-weight: bold;'
        elif "Quá khô" in status: styles[idx] = 'background-color: #FFEBEE; color: #B71C1C; font-weight: bold;'
        elif "Quá ẩm" in status: styles[idx] = 'background-color: #E3F2FD; color: #0D47A1; font-weight: bold;'
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
        
        t_val, h_val = st.session_state.temp, st.session_state.rh
        new_vpd = calculate_vpd(t_val, h_val)
        
        if new_vpd < v_min: status_text, dis_status = "⚠️ Quá ẩm", "🟦 QUÁ ẨM"
        elif new_vpd <= v_max: status_text, dis_status = "✅ Lý tưởng", "🟩 LÝ TƯỞNG"
        else: status_text, dis_status = "🚨 Quá khô", "🟥 QUÁ KHÔ"
        
        st.session_state.history.insert(0, {
            "STT": st.session_state.stt_counter, "Ngày": day_str,
            "Thời gian mô phỏng": cur_sim, "Hiển thị Giờ": cur_sim.strftime("%H:%M"),
            "datetime_internal": cur_sim, "Nhiệt độ (°C)": t_val, "Độ ẩm (%)": h_val,
            "VPD (kPa)": round(new_vpd, 2), "Trạng thái": status_text
        })
        
        url = st.session_state.discord_webhook_input
        if url and "webhooks" in url:
            sol = get_quick_solution(new_vpd, v_min, v_max, cur_sim.hour)
            u_days = sorted(list(set([r["Ngày"] for r in st.session_state.history])), reverse=True)
            lat_day = u_days[0] if u_days else day_str
            hist_lat = [r for r in st.session_state.history if r["Ngày"] == lat_day]
            trend, t_type = predict_vpd_trend_v3(hist_lat, cur_sim.hour, v_min, v_max)
            pfx = "🚨 [CẢNH BÁO SỚM] " if "CẢNH BÁO SỚM" in trend else ""
            msg = f"🌿 **HỆ THỐNG VPD ĐÀ LẠT REALTIME**\n⏰ {day_str} - {cur_sim.strftime('%H:%M')}\n📊 Môi trường: {t_val}°C | {h_val}%\n\n**1️⃣ Hiện trạng:** **{new_vpd:.2f} kPa** — {dis_status}\n**2️⃣ Biện pháp:** *{sol}*\n**3️⃣ Dự báo:** {pfx}*{trend}*"
            send_discord_message(url, msg)
        
        nxt_sim = cur_sim + timedelta(minutes=10)
        if nxt_sim.hour == 0 and nxt_sim.minute == 0:
            st.session_state.is_running = False     
            st.session_state.is_completed = True   
        st.session_state.simulated_time = nxt_sim.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        print(f"Lỗi khi trigger dữ liệu: {e}")

# --- GIAO DIỆN CHÍNH ---
def render_sidebar_controls():
    st.markdown("<h3 style='color:#2E7D32;font-size:18px;'>🤖 TRẠM ĐIỀU HÀNH</h3>", unsafe_allow_html=True)
    with st.container(border=True):
        cb1, cb2 = st.columns(2)
        with cb1:
            if st.button("▶️ Bắt đầu", type="primary", use_container_width=True, disabled=st.session_state.is_running):
                if st.session_state.is_completed: setup_next_day()
                st.session_state.is_running = True
                if st.session_state.stt_counter == 0: 
                    trigger_new_data(st.session_state.vpd_range_val[0], st.session_state.vpd_range_val[1])
                st.rerun()
        with cb2:
            if st.button("⏸️ Tạm dừng", type="secondary", use_container_width=True, disabled=not st.session_state.is_running):
                st.session_state.is_running = False
                st.rerun()
                
    with st.container(border=True):
        opt = st.selectbox("Cây trồng mô phỏng:", plant_list_keys, index=st.session_state.plant_idx, disabled=st.session_state.is_running)
        st.session_state.plant_idx = plant_list_keys.index(opt)
        v_range = DANH_SACH_CAY[opt] if opt != "🛠️ Tùy chỉnh thủ công ngưỡng riêng" else st.session_state.vpd_range_val
        vpd_sc = st.slider("Khoảng tối ưu (kPa):", 0.0, 3.0, v_range, 0.1, disabled=st.session_state.is_running or (opt != "🛠️ Tùy chỉnh thủ công ngưỡng riêng"))
        st.session_state.vpd_range_val = vpd_sc
        v_min, v_max = vpd_sc
        
    with st.container(border=True):
        st.session_state.discord_webhook_input = st.text_input("🔗 Discord Webhook URL:", value=st.session_state.discord_webhook_input, placeholder="https://...", disabled=st.session_state.is_running)

    # Hiển thị UI theo dõi (Đã rút bộ đếm ngầm ra ngoài để chống Lag)
    if st.session_state.is_running: st.caption(f"⏳ Đổi số sau: **{st.session_state.countdown}s**")
    elif st.session_state.is_completed: st.success("🏁 Hoàn thành chu kỳ ngày!")

    try: c_sim = datetime.strptime(st.session_state.simulated_time, "%Y-%m-%d %H:%M:%S")
    except Exception: c_sim = datetime.now()

    with st.container(border=True):
        st.markdown(f"⏰ **{c_sim.strftime('Ngày %d/%m')} — {c_sim.strftime('%H:%M')}**")
        c1, c2 = st.columns(2)
        c1.metric("🌡️ Nhiệt độ", f"{st.session_state.temp}°C" if st.session_state.stt_counter > 0 else "--°C")
        c2.metric("💧 Độ ẩm", f"{st.session_state.rh}%" if st.session_state.stt_counter > 0 else "--%")

    v_res = calculate_vpd(st.session_state.temp, st.session_state.rh)
    with st.container(border=True):
        st.markdown("<p style='color:#2E7D32;font-weight:bold;margin-bottom:2px;'>🎯 LỆNH ĐIỀU HÀNH</p>", unsafe_allow_html=True)
        if st.session_state.stt_counter == 0:
            st.info("Đang chờ kích hoạt...")
        else:
            lbl, color = ("🟩 LÝ TƯỞNG", "#2E7D32") if v_min <= v_res <= v_max else (("🟦 QUÁ ẨM", "#0068C9") if v_res < v_min else ("🟥 QUÁ KHÔ", "#FF4B4B"))
            u_days = sorted(list(set([r["Ngày"] for r in st.session_state.history])), reverse=True)
            hist_lat = [r for r in st.session_state.history if r["Ngày"] == (u_days[0] if u_days else c_sim.strftime("Ngày %d/%m"))]
            
            try: trnd, t_tp = predict_vpd_trend_v3(hist_lat, c_sim.hour, v_min, v_max)
            except Exception: trnd, t_tp = "Ổn định", "normal"
            
            if t_tp == "danger_red": st.markdown(f"<div class='danger-box-red'>🚨 {trnd}</div>", unsafe_allow_html=True)
            elif t_tp == "danger_blue": st.markdown(f"<div class='danger-box-blue'>🚨 {trnd}</div>", unsafe_allow_html=True)
                
            st.markdown(f"**VPD:** <span style='color:{color};font-weight:bold;font-size:16px;'>{v_res:.2f} kPa</span> ({lbl})", unsafe_allow_html=True)
            st.markdown(f"**Biện pháp:** _{get_quick_solution(v_res, v_min, v_max, c_sim.hour)}_")
            if t_tp not in ["danger_red", "danger_blue"]: st.markdown(f"**Dự báo:** {trnd}")

def render_realtime_analytics_panel():
    st.markdown("<h3 style='color:#2E7D32;font-size:18px;'>📊 TRUNG TÂM PHÂN TÍCH CHU KỲ REALTIME</h3>", unsafe_allow_html=True)
    if not st.session_state.history:
        st.info("Chưa có số liệu. Vui lòng nhấn nút Bắt đầu để tải.")
        return
        
    u_days = sorted(list(set([r["Ngày"] for r in st.session_state.history])), reverse=True)
    f1, f2 = st.columns([7, 3])
    sel_day = f1.selectbox("Lọc ngày:", u_days, label_visibility="collapsed")
    if f2.button("🗑️ Reset All", use_container_width=True):
        st.session_state.update({"stt_counter": 0, "history": [], "simulated_time": "2026-05-24 07:00:00", "is_completed": False, "is_running": False})
        st.rerun()

    df_all = pd.DataFrame(st.session_state.history)
    df_f = df_all[df_all["Ngày"] == sel_day].iloc[::-1].copy()
    v_min, v_max = st.session_state.vpd_range_val

    t1, t2, t3 = st.tabs(["📈 Biểu đồ", "📊 Thống kê buổi", "📋 Nhật ký số liệu"])
    with t1:
        st.markdown("##### 🎯 Chỉ số VPD (kPa)")
        st.altair_chart(get_vpd_chart(df_f, v_min, v_max), use_container_width=True)
        st.markdown("##### 🌡️ Tương quan Thời tiết: Nhiệt độ & Độ ẩm")
        st.altair_chart(get_weather_chart(df_f), use_container_width=True)
        
    with t2:
        try: st.dataframe(analyze_day_by_blocks_rt(st.session_state.history, v_min, v_max, sel_day), use_container_width=True, hide_index=True)
        except Exception: st.caption("Chưa đủ dữ liệu phân tích khối thời gian.")
            
    with t3:
        df_f["Thời gian"] = df_f["Hiển thị Giờ"]
        st.dataframe(df_f[["STT", "Thời gian", "Nhiệt độ (°C)", "Độ ẩm (%)", "VPD (kPa)", "Trạng thái"]].style.apply(style_status_rows, axis=1), use_container_width=True, hide_index=True)

# --- XÂY DỰNG TABS CHÍNH ---
tab_future, tab_past = st.tabs(["🔮 XEM DỰ BÁO & THEO DÕI TƯƠNG LAI", "📁 TẢI FILE & PHÂN TÍCH LỊCH SỬ"])

with tab_future:
    l_col, r_col = st.columns([3.5, 6.5])
    with l_col: render_sidebar_controls()
    with r_col: render_realtime_analytics_panel()

with tab_past:
    st.markdown("<h3 style='color:#1A5276;font-size:19px;'>📁 PHÂN TÍCH FILE IOT NHÀ KÍNH</h3>", unsafe_allow_html=True)
    tl, tr = st.columns(2)
    with tl:
        with st.container(border=True):
            st.markdown("<div class='upload-header'>🌿 1. CẤU HÌNH LOẠI CÂY TRỒNG</div>", unsafe_allow_html=True)
            f_opt = st.selectbox("Chọn mô hình cây:", plant_list_keys, index=st.session_state.file_plant_idx)
            st.session_state.file_plant_idx = plant_list_keys.index(f_opt)
            f_rng = DANH_SACH_CAY[f_opt] if f_opt != "🛠️ Tùy chỉnh thủ công ngưỡng riêng" else st.session_state.file_vpd_range_val
            f_vpd_sc = st.slider("Ngưỡng tối ưu:", 0.0, 3.0, f_rng, 0.1, disabled=(f_opt != "🛠️ Tùy chỉnh thủ công ngưỡng riêng"))
            st.session_state.file_vpd_range_val = f_vpd_sc
            f_min, f_max = f_vpd_sc
    with tr:
        with st.container(border=True):
            st.markdown("<div class='upload-header'>📥 2. TẢI DỮ LIỆU ĐẦU VÀO</div>", unsafe_allow_html=True)
            u_file = st.file_uploader("Kéo thả file:", type=["json", "csv", "xlsx"], label_visibility="collapsed")
            t_filter = st.selectbox("📆 Chế độ lọc và gộp:", [
                "📊 Xem toàn bộ dữ liệu gốc", "📆 Tự chọn ngày cụ thể", "🗓️ Chọn 1 tháng (29 ngày)", 
                "📅 Chọn 1 tuần (6 ngày)", "⏱️ 1 Ngày gần nhất (Gom 10p)", 
                "📅 1 Tuần gần nhất (Gom ngày)", "🗓️ 1 Tháng gần nhất (Gom ngày)"
            ])

    if u_file:
        try:
            # Tối ưu đọc file: Lưu cache vào bộ nhớ để chống lag khi web đếm ngược
            if "uploaded_filename" not in st.session_state or st.session_state.uploaded_filename != u_file.name:
                if u_file.name.endswith('.json'):
                    j_data = json.load(u_file)
                    st.session_state.df_raw = pd.DataFrame([j_data]) if isinstance(j_data, dict) and not isinstance(list(j_data.values())[0], (dict, list)) else pd.DataFrame(j_data)
                elif u_file.name.endswith('.csv'): 
                    st.session_state.df_raw = pd.read_csv(u_file)
                else: 
                    st.session_state.df_raw = pd.read_excel(u_file)
                st.session_state.uploaded_filename = u_file.name
                
            df_up = st.session_state.df_raw.copy()
            st.success(f"⚡ Đã đọc thành công file '{u_file.name}' với {len(df_up)} dòng dữ liệu!")
            
            with st.expander("🔍 BẤM VÀO ĐÂY ĐỂ XEM THÔNG SỐ VÀ DỮ LIỆU THÔ", expanded=False):
                st.markdown("**1. Danh sách các cột dữ liệu hiện có:**")
                st.info(", ".join(df_up.columns.astype(str).tolist()))
                st.markdown("**2. Bảng dữ liệu thô (Hiển thị 30 dòng đầu):**")
                st.dataframe(df_up.head(30), use_container_width=True)
                st.markdown("**3. Thống kê thông số cơ bản:**")
                try: st.dataframe(df_up.describe(), use_container_width=True)
                except Exception: st.caption("Không có cột số liệu chuẩn để thống kê.")
                
            cols = list(df_up.columns)
            detected_time, detected_temp, detected_humi = cols[0], cols[1] if len(cols)>1 else cols[0], cols[2] if len(cols)>2 else cols[0]
            valid_cols = [c for c in cols if df_up[c].notna().any()] or cols

            for c in valid_cols:
                cl = str(c).lower().strip()
                if any(k in cl for k in ['time', 'thời gian', 'giờ', 'gio', 'date', 'timestamp', 'created_at']): detected_time = c
                elif any(k in cl for k in ['tempkk', 'temp', 'temperature', 'nhiệt độ', 'nhiet do', 't°', 't1']): detected_temp = c
                elif any(k in cl for k in ['humikk', 'hum', 'humidity', 'độ ẩm', 'do am', 'rh', 'h1']): detected_humi = c

            st.markdown("<div class='upload-header'>🛠️ 3. ĐỒNG BỘ KHỚP CỘT DỮ LIỆU</div>", unsafe_allow_html=True)
            cc1, cc2, cc3 = st.columns(3)
            with cc1: c_time = st.selectbox("Cột chứa Thời gian:", cols, index=cols.index(detected_time) if detected_time in cols else 0)
            with cc2: c_temp = st.selectbox("Cột chứa Nhiệt độ:", cols, index=cols.index(detected_temp) if detected_temp in cols else 0)
            with cc3: c_humi = st.selectbox("Cột chứa Độ ẩm:", cols, index=cols.index(detected_humi) if detected_humi in cols else 0)

            df_rc = pd.DataFrame()
            df_rc["datetime_internal"] = pd.to_datetime(df_up[c_time].astype(str).str.strip(), errors='coerce', utc=True).dt.tz_localize(None)
            df_rc["Nhiệt độ (°C)"] = pd.to_numeric(df_up[c_temp], errors='coerce')
            df_rc["Độ ẩm (%)"] = pd.to_numeric(df_up[c_humi], errors='coerce')
            
            if df_rc["Nhiệt độ (°C)"].isna().all() or df_rc["Độ ẩm (%)"].isna().all():
                st.error("⚠️ Lỗi khớp kiểu số dữ liệu! Bạn hãy kiểm tra lại cột chứa số liệu (ví dụ: tempKK, humiKK).")
                st.stop()
            
            df_rc["datetime_internal"] = df_rc["datetime_internal"].ffill().fillna(datetime.now())
            df_rc["Nhiệt độ (°C)"] = df_rc["Nhiệt độ (°C)"].apply(lambda x: x / 10.0 if pd.notna(x) and x >= 55.0 else x)
            if df_rc["Độ ẩm (%)"].dropna().max() <= 1.05: df_rc["Độ ẩm (%)"] = df_rc["Độ ẩm (%)"] * 100.0
            
            df_rc = df_rc.dropna(subset=["Nhiệt độ (°C)", "Độ ẩm (%)"]).sort_values("datetime_internal")

            if len(df_rc) > 0:
                df_rc["VPD_raw"] = df_rc.apply(lambda r: calculate_vpd(r["Nhiệt độ (°C)"], r["Độ ẩm (%)"]), axis=1)
                df_rc["only_date"] = df_rc["datetime_internal"].dt.date
                av_dates = sorted(df_rc["only_date"].unique())
                
                if "Tự chọn ngày cụ thể" in t_filter:
                    s_date = st.date_input("👇 Chọn ngày:", value=av_dates[-1] if av_dates else datetime.now().date())
                    df_rc = df_rc[df_rc["only_date"] == s_date]
                elif "29 ngày" in t_filter:
                    st_d = st.date_input("👇 Ngày bắt đầu:", value=av_dates[0] if av_dates else datetime.now().date())
                    df_rc = df_rc[(df_rc["only_date"] >= st_d) & (df_rc["only_date"] <= st_d + timedelta(days=29))]
                elif "6 ngày" in t_filter:
                    st_d = st.date_input("👇 Ngày bắt đầu:", value=av_dates[0] if av_dates else datetime.now().date())
                    df_rc = df_rc[(df_rc["only_date"] >= st_d) & (df_rc["only_date"] <= st_d + timedelta(days=6))]
                elif "Xem toàn bộ dữ liệu gốc" in t_filter: pass
                else:
                    m_time = df_rc["datetime_internal"].max()
                    if "1 Ngày gần nhất" in t_filter: df_rc = df_rc[df_rc["datetime_internal"] >= (m_time - timedelta(days=1))]
                    elif "1 Tuần gần nhất" in t_filter: df_rc = df_rc[df_rc["datetime_internal"] >= (m_time - timedelta(days=7))]
                    elif "1 Tháng gần nhất" in t_filter: df_rc = df_rc[df_rc["datetime_internal"] >= (m_time - timedelta(days=30))]

            df_f_blk = df_rc.copy()

            if len(df_rc) > 0:
                u_days_f = df_rc["only_date"].nunique()
                df_rs = df_rc.drop_duplicates(subset=["datetime_internal"]).copy()
                df_rs = df_rs[["datetime_internal", "Nhiệt độ (°C)", "Độ ẩm (%)", "VPD_raw"]].set_index("datetime_internal")
                
                if any(k in t_filter for k in ["1 Tuần gần nhất", "1 Tháng gần nhất", "ngày"]): df_rs = df_rs.resample("1D").mean().dropna()
                elif "Xem toàn bộ dữ liệu gốc" in t_filter: df_rs = df_rs.resample("1h" if u_days_f > 2 else "10min").mean().dropna()
                elif "1 Ngày gần nhất" in t_filter: df_rs = df_rs.resample("10min").mean().dropna()
                
                df_rs["datetime_internal"] = df_rs.index
                fmt = "%d/%m %H:%M" if (any(k in t_filter for k in ["1 Tuần gần nhất", "1 Tháng gần nhất", "ngày"]) or ("Xem toàn bộ dữ liệu gốc" in t_filter and u_days_f > 2)) else "%H:%M"
                df_rs["Hiển thị Giờ"] = df_rs["datetime_internal"].dt.strftime(fmt)
                df_rs.reset_index(drop=True, inplace=True)
            else:
                df_rs = pd.DataFrame(columns=["datetime_internal", "Nhiệt độ (°C)", "Độ ẩm (%)", "VPD_raw", "Hiển thị Giờ"])

            df_p = pd.DataFrame()
            if len(df_rs) > 0:
                df_p["datetime_internal"] = df_rs["datetime_internal"]
                df_p["Nhiệt độ (°C)"] = df_rs["Nhiệt độ (°C)"].round(2)
                df_p["Độ ẩm (%)"] = df_rs["Độ ẩm (%)"].round(2)
                df_p["Hiển thị Giờ"] = df_rs["Hiển thị Giờ"]
                df_p["VPD (kPa)"] = df_rs["VPD_raw"].round(2)
                df_p["Ngày"] = "Dữ liệu File"
                df_p["Trạng thái"] = df_p["VPD (kPa)"].apply(lambda x: "⚠️ Quá ẩm" if x < f_min else ("✅ Lý tưởng" if x <= f_max else "🚨 Quá khô"))
            else:
                st.warning("⚠️ Không tìm thấy dữ liệu phù hợp với bộ lọc thời gian!")
                st.stop()
            
            st.markdown("<div style='margin-top:15px;margin-bottom:5px;font-weight:bold;color:#1A5276;'>📊 TỔNG QUAN CHU KỲ GỘP</div>", unsafe_allow_html=True)
            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.markdown(f"<div class='metric-card-upload'><span>📈 VPD TB CHU KỲ</span><br><b style='font-size:18px;color:#2E7D32;'>{df_p['VPD (kPa)'].mean():.2f} kPa</b></div>", unsafe_allow_html=True)
            mc2.markdown(f"<div class='metric-card-upload'><span>🌡️ NHIỆT ĐỘ TB</span><br><b style='font-size:18px;color:#FF4B4B;'>{df_p['Nhiệt độ (°C)'].mean():.1f} °C</b></div>", unsafe_allow_html=True)
            mc3.markdown(f"<div class='metric-card-upload'><span>💧 ĐỘ ẨM TB</span><br><b style='font-size:18px;color:#0068C9;'>{df_p['Độ ẩm (%)'].mean():.1f} %</b></div>", unsafe_allow_html=True)
            mc4.markdown(f"<div class='metric-card-upload'><span>📋 SỐ ĐIỂM DỮ LIỆU</span><br><b style='font-size:18px;color:#5D6D7E;'>{len(df_p)} điểm</b></div>", unsafe_allow_html=True)

            rl, rr = st.columns([6.2, 3.8])
            with rl:
                st.markdown("#### 📊 BIỂU ĐỒ CHU KỲ PHÂN TẦNG")
                st.altair_chart(get_vpd_chart(df_p, f_min, f_max), use_container_width=True)
            with rr:
                st.markdown("##### 📋 NHẬT KÝ THEO DÕI ĐIỂM GỘP CHU KỲ")
                df_tc = df_p[["Hiển thị Giờ", "Nhiệt độ (°C)", "Độ ẩm (%)", "VPD (kPa)", "Trạng thái"]].copy()
                for c in ["Nhiệt độ (°C)", "Độ ẩm (%)", "VPD (kPa)"]: df_tc[c] = df_tc[c].apply(lambda x: f"{float(x):.2f}")
                st.dataframe(df_tc.style.apply(style_status_rows, axis=1), use_container_width=True, hide_index=True, height=290)

            st.markdown("---")
            if len(df_f_blk) > 0:
                df_f_blk["Hour"] = df_f_blk["datetime_internal"].dt.hour
                def b_assign(h):
                    if 5 <= h < 10: return "🌅 Sáng (05h - 10h)"
                    if 10 <= h < 15: return "☀️ Trưa (10h - 15h)"
                    if 15 <= h < 19: return "🌇 Chiều (15h - 19h)"
                    if 19 <= h < 23: return "🌌 Tối (19h - 23h)"
                    return "🌙 Khuya (23h - 05h)"
                df_f_blk["Buổi"] = df_f_blk["Hour"].apply(b_assign)
                b_sum = df_f_blk.groupby("Buổi").agg({"Nhiệt độ (°C)": "mean", "Độ ẩm (%)": "mean", "VPD_raw": "mean"}).reindex(["🌅 Sáng (05h - 10h)", "☀️ Trưa (10h - 15h)", "🌇 Chiều (15h - 19h)", "🌌 Tối (19h - 23h)", "🌙 Khuya (23h - 05h)"]).dropna(how="all").reset_index()
                b_sum.columns = ["Khoảng thời gian", "Nhiệt độ TB (°C)", "Độ ẩm TB (%)", "VPD TB (kPa)"]
                for c in ["Nhiệt độ TB (°C)", "Độ ẩm TB (%)", "VPD TB (kPa)"]: b_sum[c] = b_sum[c].round(2)
                b_sum["Đánh giá"] = b_sum["VPD TB (kPa)"].apply(lambda x: "🟦 Quá ẩm" if x < f_min else ("🟩 Lý tưởng" if x <= f_max else "🟥 Quá khô"))
                st.dataframe(b_sum, use_container_width=True, hide_index=True)
                
        except Exception as file_err:
            st.error(f"❌ Không thể xử lý file này: {str(file_err)}")

# --- VÒNG LẶP THỜI GIAN THỰC ĐỂ MÔ PHỎNG (SẠCH - KHÔNG GÂY ĐƠ WEB) ---
if st.session_state.is_running:
    time.sleep(1)
    st.session_state.countdown -= 1
    if st.session_state.countdown <= 0:
        trigger_new_data(st.session_state.vpd_range_val[0], st.session_state.vpd_range_val[1])
    st.rerun()
