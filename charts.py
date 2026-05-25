import altair as alt
import pandas as pd

def draw_vpd_chart(df, vpd_min, vpd_max):
    if df.empty:
        return alt.Chart(pd.DataFrame()).mark_blank()
    
    # 1. Đồng bộ cấu trúc dữ liệu bảng biểu, map các cột hằng số biên tĩnh làm mỏ neo cho tham số Y2 của dải nền
    df_chart = df.copy()
    df_chart['y_min_bound'] = vpd_min
    df_chart['y_max_bound'] = vpd_max
    df_chart['y_floor'] = 0.0
    df_chart['y_roof'] = 3.0

    # 2. Định nghĩa trục X dùng chung ép kiểu Ordinal (:O) giúp gộp điểm sạch mượt và chống lặp mốc 00:00
    x_axis = alt.X(field='Hiển thị Giờ', type='ordinal', title='Mốc thời gian chu kỳ', sort=None)

    # 3. Xây dựng 3 lớp dải màu nền động bám biên dữ liệu gốc (Sử dụng chuẩn xác tham số Y và Y2)
    bg_under = alt.Chart(df_chart).mark_area(color='#E3F2FD', opacity=0.9).encode(
        x=x_axis,
        y=alt.Y(field='y_floor', type='quantitative'),
        y2=alt.Y2(field='y_min_bound')
    )
    
    bg_ideal = alt.Chart(df_chart).mark_area(color='#E8F5E9', opacity=0.9).encode(
        x=x_axis,
        y=alt.Y(field='y_min_bound', type='quantitative'),
        y2=alt.Y2(field='y_max_bound')
    )
    
    bg_over = alt.Chart(df_chart).mark_area(color='#FFEBEE', opacity=0.9).encode(
        x=x_axis,
        y=alt.Y(field='y_max_bound', type='quantitative'),
        y2=alt.Y2(field='y_roof')
    )

    # 4. Vẽ đường đồ thị chính và các điểm tròn tương tác Tooltip
    line = alt.Chart(df_chart).mark_line(color='#2E7D32', strokeWidth=3.5).encode(
        x=x_axis,
        y=alt.Y(field='VPD (kPa)', type='quantitative', title='Chỉ số VPD (kPa)', scale=alt.Scale(domain=[0, 3.0], clamp=True))
    )
    
    points = alt.Chart(df_chart).mark_circle(color='#1B5E20', size=70).encode(
        x=x_axis,
        y=alt.Y(field='VPD (kPa)', type='quantitative'),
        tooltip=['Hiển thị Giờ', 'Nhiệt độ (°C)', 'Độ ẩm (%)', 'VPD (kPa)', 'Trạng thái']
    )

    # Lồng lớp xếp dải màu nền dưới cùng, đường kẻ lên trên cùng và kích hoạt Zoom tương tác (.interactive)
    return alt.layer(bg_under, bg_ideal, bg_over, line, points).properties(height=280).interactive().configure_axis(labelAngle=0)

def draw_temperature_chart(df):
    if df.empty: 
        return alt.Chart(pd.DataFrame()).mark_blank()
    return alt.Chart(df).mark_line(color='#FF4B4B', strokeWidth=2.5).encode(
        x=alt.X(field='Hiển thị Giờ', type='ordinal', title='Mốc thời gian', sort=None),
        y=alt.Y(field='Nhiệt độ (°C)', type='quantitative', title='Nhiệt độ (°C)'),
        tooltip=['Hiển thị Giờ', 'Nhiệt độ (°C)']
    ).properties(height=280).interactive().configure_axis(labelAngle=0)

def draw_humidity_chart(df):
    if df.empty: 
        return alt.Chart(pd.DataFrame()).mark_blank()
    return alt.Chart(df).mark_line(color='#0068C9', strokeWidth=2.5).encode(
        x=alt.X(field='Hiển thị Giờ', type='ordinal', title='Mốc thời gian', sort=None),
        y=alt.Y(field='Độ ẩm (%)', type='quantitative', title='Độ ẩm (%)'),
        tooltip=['Hiển thị Giờ', 'Độ ẩm (%)']
    ).properties(height=280).interactive().configure_axis(labelAngle=0)

def draw_combined_chart(df):
    if df.empty: 
        return alt.Chart(pd.DataFrame()).mark_blank()
    
    x_axis = alt.X(field='Hiển thị Giờ', type='ordinal', title='Mốc thời gian', sort=None)
    
    line1 = alt.Chart(df).mark_line(color='#FF4B4B', strokeWidth=2).encode(x=x_axis, y=alt.Y(field='Nhiệt độ (°C)', type='quantitative', title='Nhiệt độ & Độ ẩm'))
    line2 = alt.Chart(df).mark_line(color='#0068C9', strokeWidth=2).encode(x=x_axis, y=alt.Y(field='Độ ẩm (%)', type='quantitative'))
    line3 = alt.Chart(df).mark_line(color='#2E7D32', strokeWidth=3.5).encode(x=x_axis, y=alt.Y(field='VPD (kPa)', type='quantitative'))
    
    return alt.layer(line1, line2, line3).properties(height=280).interactive().configure_axis(labelAngle=0)
