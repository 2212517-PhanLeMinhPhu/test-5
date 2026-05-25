import math
import random

def calculate_vpd(temp, rh):
    """Tính toán chỉ số áp suất hơi thâm hụt (VPD)"""
    if temp == 0 and rh == 0:
        return 0.0
    vp_sat = 0.61078 * math.exp((17.27 * temp) / (temp + 237.3))
    vpd = vp_sat * (1.0 - (rh / 100.0))
    return vpd

def get_weather_by_time(sim_time):
    """Mô phỏng thời tiết ngẫu nhiên theo chu kỳ buổi trong ngày ở Đà Lạt"""
    hour = sim_time.hour
    if 7 <= hour < 11:
        temp = round(random.uniform(20.0, 25.5), 1)
        rh = round(random.uniform(65.0, 80.0), 1)
    elif 11 <= hour < 15:
        temp = round(random.uniform(26.0, 31.0), 1)
        rh = round(random.uniform(40.0, 55.0), 1)
    elif 15 <= hour < 19:
        temp = round(random.uniform(19.0, 25.0), 1)
        rh = round(random.uniform(60.0, 75.0), 1)
    else:
        temp = round(random.uniform(14.0, 18.5), 1)
        rh = round(random.uniform(80.0, 95.0), 1)
    return temp, rh
