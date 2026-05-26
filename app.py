st.markdown("""##### 📋 NHẬT KÝ THEO DÕI ĐIỂM GỘP CHU KỲ""")
            
            # Khởi tạo bảng hiển thị
            df_tc = df_p[["Hiển thị Giờ", "Nhiệt độ (°C)", "Độ ẩm (%)", "VPD (kPa)", "Trạng thái"]].copy()
            
            # Ép kiểu dữ liệu hiển thị đồng nhất 2 số thập phân
            for c in ["Nhiệt độ (°C)", "Độ ẩm (%)", "VPD (kPa)"]: 
                df_tc[c] = df_tc[c].apply(lambda x: f"{float(x):.2f}")
            
            # Đổi tên cột hiển thị RÕ RÀNG là "trung bình"
            df_tc = df_tc.rename(columns={
                "Hiển thị Giờ": "Thời gian (Chu kỳ)",
                "Nhiệt độ (°C)": "Nhiệt độ trung bình (°C)",
                "Độ ẩm (%)": "Độ ẩm trung bình (%)",
                "VPD (kPa)": "VPD trung bình (kPa)",
                "Trạng thái": "Trạng thái"
            })
            
            # Hiển thị lên giao diện
            st.dataframe(df_tc.style.apply(style_status_rows, axis=1), use_container_width=True, hide_index=True, height=350)
            
            # Đồng bộ tên cột trung bình vào file CSV tải xuống
            df_download = df_tc.copy()
            csv_data = df_download.to_csv(index=False).encode('utf-8')
            st.download_button(
                """📥 Xuất báo cáo chu kỳ (.csv)""", 
                data=csv_data, 
                file_name="vpd_report.csv", 
                mime="text/csv", 
                use_container_width=True
            )
