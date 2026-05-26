import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta
import sys
import os
import time
import altair as alt

# --- TÌM KIẾM MODULE ---
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from calculations import calculate_vpd, get_weather_by_time
    from services import send_discord_message, get_quick_solution
    from analytics import analyze_day_by_blocks_rt, predict_vpd_trend_v3, calculate_plant_stress_hours
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

# Khởi tạo Session State
for key, val in {
    "temp": 0.0, "rh": 0.0, "countdown": 15, "is_running": False, 
    "is_completed": False, "history": [], "stt_counter": 0, 
    "plant_idx": 0, "vpd_range_val": (0.6, 1.1), 
    "simulated_time": "2026-05-24 07:00:00", "file_plant_idx": 0,
    "file_vpd_range_val": (0.6, 1.1), "discord_webhook_input": ""
}.items():
    if key not in st.session_state:
        st.session_state[key] = val

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

# --- CÁC HÀM CACHE TỐI ƯU HÓA HIỆU NĂNG ---
# 1. Cache việc đọc file thô (Chỉ đọc 1 lần duy nhất)
@st.cache_data(max_entries=1)
def load_raw_file(file_obj, filename):
    if filename.endswith('.json'):
        j_data = json.load(file_obj)
        return pd.DataFrame([j_data]) if isinstance(j_data, dict) and not isinstance(list(j_data.values())[0], (dict, list)) else pd.DataFrame(j_data)
    elif filename.endswith('.csv'):
        return pd.read_csv(file_obj)
    else:
        return pd.read_excel(file_obj)

# 2. Cache các tác vụ xử lý Pandas nặng (Lọc, Resample, Gom nhóm)
@st.cache_data(max_entries=3)
def process_dataframe(df_raw, c_time, c_temp, c_humi, t_filter, f_min, f_max):
    df_rc = pd.DataFrame()
    df_rc["datetime_internal"] = pd.to_datetime(df_raw[c_time].astype(str).str.strip(), errors='coerce', utc=True).dt.tz_localize(None)
    df_rc["Nhiệt độ (°C)"] = pd.to_numeric(df_raw[c_temp], errors='coerce')
    df_rc["Độ ẩm (%)"] = pd.to_numeric(df_raw[c_humi], errors='coerce')
    
    if df_rc["Nhiệt độ (°C)"].isna().all() or df_rc["Độ ẩm (%)"].isna().all():
        return None, None, "⚠️ Lỗi khớp kiểu số dữ liệu!"
        
    df_rc["datetime_internal"] = df_rc["datetime_internal"].ffill().fillna(datetime.now())
    df_rc["Nhiệt độ (°C)"] = df_rc["Nhiệt độ (°C)"].apply(lambda x: x / 10.0 if pd.notna(x) and x >= 55.0 else x)
    if df_rc["Độ ẩm (%)"].dropna().max() <= 1.05: df_rc["Độ ẩm (%)"] = df_rc["Độ ẩm (%)"] * 100.0
    
    df_rc = df_rc.dropna(subset=["Nhiệt độ (°C)", "Độ ẩm (%)"]).sort_values("datetime_internal")
    
    if len(df_rc) == 0:
        return pd.DataFrame(), pd.DataFrame(), ""

    df_rc["VPD_raw"] = df_rc.apply(lambda r: calculate_vpd(r["Nhiệt độ (°C)"], r["Độ ẩm (%)"]), axis=1)
    df_rc["only_date"] = df_rc["datetime_internal"].dt.date
    m_time = df_rc["datetime_internal"].max()

    # Áp dụng bộ lọc
    if "1 Ngày gần nhất" in t_filter: df_rc = df_rc[df_rc["datetime_internal"] >= (m_time - timedelta(days=1))]
    elif "1 Tuần gần nhất" in t_filter: df_rc = df_rc[df_rc["datetime_internal"] >= (m_time - timedelta(days=7))]
    elif "1 Tháng gần nhất" in t_filter: df_rc = df_rc[df_rc["datetime_internal"] >= (m_time - timedelta(days=30))]
    
    df_f_blk = df_rc.copy()
    u_days_f = df_rc["only_date"].nunique()
    
    df_rs = df_rc.drop_duplicates(subset=["datetime_internal"]).copy()
    df_rs = df_rs[["datetime_internal", "Nhiệt độ (°C)", "Độ ẩm (%)", "VPD_raw"]].set_index("datetime_internal")
    
    if any(k in t_filter for k in ["1 Tuần", "1 Tháng", "ngày"]): df_rs = df_rs.resample("1D").mean().dropna()
    elif "Xem toàn bộ" in t_filter: df_rs = df_rs.resample("1h" if u_days_f > 2 else "10min").mean().dropna()
    elif "1 Ngày gần nhất" in t_filter: df_rs = df_rs.resample("10min").mean().dropna()
    
    df_rs["datetime_internal"] = df_rs.index
    fmt = "%d/%m %H:%M" if (any(k in t_filter for k in ["1 Tuần", "1 Tháng", "ngày"]) or ("Xem toàn bộ" in t_filter and u_days_f > 2)) else "%H:%M"
    df_rs["Hiển thị Giờ"] = df_rs["datetime_internal"].dt.strftime(fmt)
    df_rs.reset_index(drop=True, inplace=True)
    
    df_p = pd.DataFrame()
    if len(df_rs) > 0:
        df_p["datetime_internal"] = df_rs["datetime_internal"]
        df_p["Nhiệt độ (°C)"] = df_rs["Nhiệt độ (°C)"].round(2)
        df_p["Độ ẩm (%)"] = df_rs["Độ ẩm (%)"].round(2)
        df_p["Hiển thị Giờ"] = df_rs["Hiển thị Giờ"]
        df_p["VPD (kPa)"] = df_rs["VPD_raw"].round(2)
        df_p["Ngày"] = "Dữ liệu File"
        df_p["Trạng thái"] = df_p["VPD (kPa)"].apply(lambda x: "⚠️ Quá ẩm" if x < f_min else ("✅ Lý tưởng" if x <= f_max else "🚨 Quá khô"))
        
    return df_p, df_f_blk, ""

# --- HÀM VẼ BIỂU ĐỒ & BỔ TRỢ (Giữ nguyên) ---
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

def style_status_rows(row):
    styles = [''] * len(row)
    if 'Trạng thái' in row.index:
        idx = row.index.get_loc('Trạng thái')
        status = str(row['Trạng thái'])
        if "Lý tưởng" in status: styles[idx] = 'background-color: #E8F5E9; color: #1B5E20; font-weight: bold;'
        elif "Quá khô" in status: styles[idx] = 'background-color: #FFEBEE; color: #B71C1C; font-weight: bold;'
        elif "Quá ẩm" in status: styles[idx] = 'background-color: #E3F2FD; color: #0D47A1; font-weight: bold;'
    return styles

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
        
        nxt_sim = cur_sim + timedelta(minutes=10)
        if nxt_sim.hour == 0 and nxt_sim.minute == 0:
            st.session_state.is_running = False     
            st.session_state.is_completed = True   
        st.session_state.simulated_time = nxt_sim.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        print(f"Lỗi: {e}")

# --- GIAO DIỆN CHÍNH ---
tab_future, tab_past = st.tabs(["🔮 XEM DỰ BÁO & THEO DÕI TƯƠNG LAI", "📁 TẢI FILE & PHÂN TÍCH LỊCH SỬ"])

with tab_future:
    l_col, r_col = st.columns([3.5, 6.5])
    with l_col:
        st.markdown("<h3 style='color:#2E7D32;font-size:18px;'>🤖 TRẠM ĐIỀU HÀNH</h3>", unsafe_allow_html=True)
        with st.container(border=True):
            cb1, cb2 = st.columns(2)
            with cb1:
                if st.button("▶️ Bắt đầu", type="primary", use_container_width=True, disabled=st.session_state.is_running):
                    if st.session_state.is_completed: 
                        st.session_state.simulated_time = "2026-05-24 07:00:00"
                        st.session_state.is_completed = False
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

        if st.session_state.is_running: st.caption(f"⏳ Đổi số sau: **{st.session_state.countdown}s**")
        elif st.session_state.is_completed: st.success("🏁 Hoàn thành chu kỳ ngày!")

        try: c_sim = datetime.strptime(st.session_state.simulated_time, "%Y-%m-%d %H:%M:%S")
        except: c_sim = datetime.now()

        with st.container(border=True):
            st.markdown(f"⏰ **{c_sim.strftime('Ngày %d/%m')} — {c_sim.strftime('%H:%M')}**")
            c1, c2 = st.columns(2)
            c1.metric("🌡️ Nhiệt độ", f"{st.session_state.temp}°C" if st.session_state.stt_counter > 0 else "--°C")
            c2.metric("💧 Độ ẩm", f"{st.session_state.rh}%" if st.session_state.stt_counter > 0 else "--%")

    with r_col:
        st.markdown("<h3 style='color:#2E7D32;font-size:18px;'>📊 TRUNG TÂM PHÂN TÍCH CHU KỲ REALTIME</h3>", unsafe_allow_html=True)
        if not st.session_state.history:
            st.info("Chưa có số liệu. Vui lòng nhấn nút Bắt đầu để tải.")
        else:
            u_days = sorted(list(set([r["Ngày"] for r in st.session_state.history])), reverse=True)
            f1, f2 = st.columns([7, 3])
            sel_day = f1.selectbox("Lọc ngày:", u_days, label_visibility="collapsed")
            if f2.button("🗑️ Reset All", use_container_width=True):
                st.session_state.update({"stt_counter": 0, "history": [], "simulated_time": "2026-05-24 07:00:00", "is_completed": False, "is_running": False})
                st.rerun()

            df_all = pd.DataFrame(st.session_state.history)
            df_f = df_all[df_all["Ngày"] == sel_day].iloc[::-1].copy()

            t1, t2 = st.tabs(["📈 Biểu đồ", "📋 Nhật ký"])
            with t1:
                st.altair_chart(get_vpd_chart(df_f, v_min, v_max), use_container_width=True)
            with t2:
                df_f["Thời gian"] = df_f["Hiển thị Giờ"]
                st.dataframe(df_f[["STT", "Thời gian", "Nhiệt độ (°C)", "Độ ẩm (%)", "VPD (kPa)", "Trạng thái"]].style.apply(style_status_rows, axis=1), use_container_width=True, hide_index=True)

with tab_past:
    st.markdown("<h3 style='color:#1A5276;font-size:19px;'>📁 PHÂN TÍCH FILE IOT NHÀ KÍNH</h3>", unsafe_allow_html=True)
    tl, tr = st.columns(2)
    with tl:
        with st.container(border=True):
            st.markdown("<div class='upload-header'>🌿 1. CẤU HÌNH LOẠI CÂY TRỒNG</div>", unsafe_allow_html=True)
            f_opt = st.selectbox("Chọn mô hình cây:", plant_list_keys, index=st.session_state.file_plant_idx)
            f_rng = DANH_SACH_CAY[f_opt] if f_opt != "🛠️ Tùy chỉnh thủ công ngưỡng riêng" else st.session_state.file_vpd_range_val
            f_min, f_max = st.slider("Ngưỡng tối ưu:", 0.0, 3.0, f_rng, 0.1, disabled=(f_opt != "🛠️ Tùy chỉnh thủ công ngưỡng riêng"))
    with tr:
        with st.container(border=True):
            st.markdown("<div class='upload-header'>📥 2. TẢI DỮ LIỆU ĐẦU VÀO</div>", unsafe_allow_html=True)
            u_file = st.file_uploader("Kéo thả file:", type=["json", "csv", "xlsx"], label_visibility="collapsed")
            t_filter = st.selectbox("📆 Chế độ lọc và gộp:", [
                "📊 Xem toàn bộ dữ liệu gốc", "⏱️ 1 Ngày gần nhất (Gom 10p)", 
                "📅 1 Tuần gần nhất (Gom ngày)", "🗓️ 1 Tháng gần nhất (Gom ngày)"
            ])

    if u_file:
        try:
            # Load raw data cached
            df_up = load_raw_file(u_file, u_file.name)
            st.success(f"⚡ Đã đọc file '{u_file.name}' - {len(df_up)} dòng!")
                
            cols = list(df_up.columns)
            valid_cols = [c for c in cols if df_up[c].notna().any()] or cols
            detected_time, detected_temp, detected_humi = cols[0], cols[1] if len(cols)>1 else cols[0], cols[2] if len(cols)>2 else cols[0]

            for c in valid_cols:
                cl = str(c).lower().strip()
                if any(k in cl for k in ['time', 'date', 'timestamp']): detected_time = c
                elif any(k in cl for k in ['temp', 'nhiệt độ', 't1']): detected_temp = c
                elif any(k in cl for k in ['hum', 'độ ẩm', 'rh']): detected_humi = c

            st.markdown("<div class='upload-header'>🛠️ 3. ĐỒNG BỘ CỘT DỮ LIỆU</div>", unsafe_allow_html=True)
            cc1, cc2, cc3 = st.columns(3)
            with cc1: c_time = st.selectbox("Thời gian:", cols, index=cols.index(detected_time) if detected_time in cols else 0)
            with cc2: c_temp = st.selectbox("Nhiệt độ:", cols, index=cols.index(detected_temp) if detected_temp in cols else 0)
            with cc3: c_humi = st.selectbox("Độ ẩm:", cols, index=cols.index(detected_humi) if detected_humi in cols else 0)

            # Xử lý data cached
            df_p, df_f_blk, err = process_dataframe(df_up, c_time, c_temp, c_humi, t_filter, f_min, f_max)
            
            if err: st.error(err)
            elif df_p is not None and len(df_p) > 0:
                st.markdown("<div style='margin-top:15px;margin-bottom:5px;font-weight:bold;color:#1A5276;'>📊 TỔNG QUAN CHU KỲ GỘP</div>", unsafe_allow_html=True)
                mc1, mc2, mc3, mc4 = st.columns(4)
                mc1.markdown(f"<div class='metric-card-upload'><span>📈 VPD TB</span><br><b style='font-size:18px;color:#2E7D32;'>{df_p['VPD (kPa)'].mean():.2f} kPa</b></div>", unsafe_allow_html=True)
                mc2.markdown(f"<div class='metric-card-upload'><span>🌡️ NHIỆT ĐỘ</span><br><b style='font-size:18px;color:#FF4B4B;'>{df_p['Nhiệt độ (°C)'].mean():.1f} °C</b></div>", unsafe_allow_html=True)
                mc3.markdown(f"<div class='metric-card-upload'><span>💧 ĐỘ ẨM</span><br><b style='font-size:18px;color:#0068C9;'>{df_p['Độ ẩm (%)'].mean():.1f} %</b></div>", unsafe_allow_html=True)
                mc4.markdown(f"<div class='metric-card-upload'><span>📋 SỐ ĐIỂM</span><br><b style='font-size:18px;color:#5D6D7E;'>{len(df_p)}</b></div>", unsafe_allow_html=True)

                rl, rr = st.columns([6.2, 3.8])
                with rl: st.altair_chart(get_vpd_chart(df_p, f_min, f_max), use_container_width=True)
                with rr:
                    df_tc = df_p[["Hiển thị Giờ", "Nhiệt độ (°C)", "Độ ẩm (%)", "VPD (kPa)", "Trạng thái"]].copy()
                    st.dataframe(df_tc.style.apply(style_status_rows, axis=1), use_container_width=True, hide_index=True, height=350)
            else:
                st.warning("⚠️ Không có dữ liệu hợp lệ sau khi xử lý.")
        except Exception as file_err:
            st.error(f"❌ Có lỗi: {str(file_err)}")

# --- VÒNG LẶP ĐẾM NGƯỢC (Tối ưu) ---
if st.session_state.is_running:
    time.sleep(1)
    st.session_state.countdown -= 1
    if st.session_state.countdown <= 0:
        trigger_new_data(st.session_state.vpd_range_val[0], st.session_state.vpd_range_val[1])
    # Do ứng dụng đã có bộ đệm Cache, thao tác rerun này giờ chỉ mất vài phần nghìn giây.
    st.rerun()
