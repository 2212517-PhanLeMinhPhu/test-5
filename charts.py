import altair as alt
import pandas as pd

def draw_vpd_chart(df, vpd_min, vpd_max):
    # SỬA LỖI TẠI ĐÂY: Thay mark_blank() bằng cách trả về khung chữ thông báo trống
    if df.empty:
        return alt.Chart(pd.DataFrame({'text': ['Không có dữ liệu']})).mark_text().encode(text='text:N')
    
    df_chart = df.copy()
    
    # Kỹ thuật giãn nhãn chữ chống đè chữ khi dữ liệu dày
    use_thinning = len(df_chart) > 30

    x_axis = alt.X(
        field='Hiển thị Giờ', 
        type='ordinal', 
        title='Mốc thời gian chu kỳ', 
        sort=None,
        axis=alt.Axis(
            labelAngle=-45 if use_thinning else 0,
            labelExpr="datum.index % " + str(max(1, len(df_chart) // 10)) + " == 0 ? datum.label : ''" if use_thinning else "datum.label"
        )
    )

    # NỀN TĨNH: Vẽ dải màu phân tầng độc lập toàn khung hình khối chữ nhật (mark_rect)
    bg_under = alt.Chart(df_chart).mark_rect(color='#E3F2FD', opacity=0.7).encode(
        y=alt.Y(datum=0.0, type='quantitative'),
        y2=alt.Y2(datum=vpd_min)
    )
    bg_ideal = alt.Chart(df_chart).mark_rect(color='#E8F5E9', opacity=0.7).encode(
        y=alt.Y(datum=vpd_min, type='quantitative'),
        y2=alt.Y2(datum=vpd_max)
    )
    bg_over = alt.Chart(df_chart).mark_rect(color='#FFEBEE', opacity=0.7).encode(
        y=alt.Y(datum=vpd_max, type='quantitative'),
        y2=alt.Y2(datum=3.0)
    )

    # Đường đồ thị chính và điểm Tooltip tương tác
    line = alt.Chart(df_chart).mark_line(color='#2E7D32', strokeWidth=3.5).encode(
        x=x_axis,
        y=alt.Y('VPD (kPa):Q', title='Chỉ số VPD (kPa)', scale=alt.Scale(domain=[0, 3.0], clamp=True))
    )
    
    points = alt.Chart(df_chart).mark_circle(color='#1B5E20', size=45).encode(
        x=x_axis,
        y=alt.Y('VPD (kPa):Q'),
        tooltip=[
            alt.Tooltip('Hiển thị Giờ', title='Thời gian'),
            alt.Tooltip('Nhiệt độ (°C)', title='Nhiệt độ (°C)'),
            alt.Tooltip('Độ ẩm (%)', title='Độ ẩm (%)'),
            alt.Tooltip('VPD (kPa)', title='VPD (kPa)'),
            alt.Tooltip('Trạng thái', title='Trạng thái')
        ]
    )

    return alt.layer(bg_under, bg_ideal, bg_over, line, points).properties(
        height=220
    ).interactive(bind_y=False)


def draw_weather_combined_chart(df):
    # SỬA LỖI TẠI ĐÂY: Thay mark_blank() bằng cách trả về khung chữ thông báo trống
    if df.empty: 
        return alt.Chart(pd.DataFrame({'text': ['Không có dữ liệu']})).mark_text().encode(text='text:N')
    
    use_thinning = len(df) > 30
    x_axis = alt.X(
        field='Hiển thị Giờ', type='ordinal', title='Mốc thời gian', sort=None,
        axis=alt.Axis(
            labelAngle=-45 if use_thinning else 0,
            labelExpr="datum.index % " + str(max(1, len(df) // 10)) + " == 0 ? datum.label : ''" if use_thinning else "datum.label"
        )
    )
    
    # 1. Khởi tạo đồ thị NHIỆT ĐỘ (Trục Y bên trái - Màu Đỏ)
    temp_line = alt.Chart(df).mark_line(color='#FF4B4B', strokeWidth=2.5).encode(
        x=x_axis,
        y=alt.Y('Nhiệt độ (°C):Q', title='Nhiệt độ (°C)', scale=alt.Scale(zero=False))
    )
    temp_points = alt.Chart(df).mark_circle(color='#B71C1C', size=35).encode(
        x=x_axis,
        y=alt.Y('Nhiệt độ (°C):Q'),
        tooltip=['Hiển thị Giờ', 'Nhiệt độ (°C)', 'Độ ẩm (%)', 'VPD (kPa)', 'Trạng thái']
    )
    temp_chart = alt.layer(temp_line, temp_points)

    # 2. Khởi tạo đồ thị ĐỘ ẨM (Trục Y bên phải - Màu Xanh)
    humi_line = alt.Chart(df).mark_line(color='#0068C9', strokeWidth=2.5).encode(
        x=x_axis,
        y=alt.Y('Độ ẩm (%):Q', title='Độ ẩm (%)', scale=alt.Scale(domain=[0, 100]))
    )
    humi_points = alt.Chart(df).mark_circle(color='#0D47A1', size=35).encode(
        x=x_axis,
        y=alt.Y('Độ ẩm (%):Q'),
        tooltip=['Hiển thị Giờ', 'Nhiệt độ (°C)', 'Độ ẩm (%)', 'VPD (kPa)', 'Trạng thái']
    )
    humi_chart = alt.layer(humi_line, humi_points)

    # 3. Kết hợp trục kép độc lập (Dual Axis) và khóa Zoom trục dọc Y
    return alt.layer(temp_chart, humi_chart).resolve_scale(
        y='independent'
    ).properties(
        height=200
    ).interactive(bind_y=False)
