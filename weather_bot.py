import math
import os
import time
import hmac
import hashlib
import base64
import requests
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus
from dateutil import parser


# ------ 配置部分 ------
QWEATHER_HOST = os.getenv("QWEATHER_HOST", "https://mu5pwc6q8d.re.qweatherapi.com")
QWEATHER_API_KEY = os.environ["QWEATHER_API_KEY"]
LOCATION = os.environ["LOCATION"]

DINGTALK_WEBHOOK = os.environ["DINGTALK_WEBHOOK"]
DINGTALK_SECRET = os.environ["DINGTALK_SECRET"]
# ----------------------


def get_now_weather():
    url = f"{QWEATHER_HOST}/v7/weather/now"
    params = {
        "location": LOCATION,
        "key": QWEATHER_API_KEY,
        "lang": "zh",
        "unit": "m"
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_hourly_forecast():
    url = f"{QWEATHER_HOST}/v7/weather/24h"
    params = {
        "location": LOCATION,
        "key": QWEATHER_API_KEY,
        "lang": "zh",
        "unit": "m"
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_alerts():
    url = f"{QWEATHER_HOST}/v7/warning/now"
    params = {
        "location": LOCATION,
        "key": QWEATHER_API_KEY
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_air_quality():
    url = f"{QWEATHER_HOST}/v7/air/now"
    params = {
        "location": LOCATION,
        "key": QWEATHER_API_KEY
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def filter_next_4h(hours_data):
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    end_utc = now_utc + timedelta(hours=4)

    out = []

    for item in hours_data:
        fx_time = parser.isoparse(item["fxTime"])

        if now_utc < fx_time <= end_utc:
            out.append(item)

    return out


def format_time_bj(iso_str):
    dt = parser.isoparse(iso_str).astimezone(timezone(timedelta(hours=8)))
    return dt.strftime("%H:%M")


def icon_to_emoji(icon):

    icon_map = {
        "100": "☀️", "101": "🌤", "102": "⛅", "103": "🌥", "104": "☁️",
        "150": "🌫", "151": "🌁", "153": "🌁",
        "300": "🌧", "301": "🌦", "302": "⛈", "303": "⛈", "304": "🌩",
        "305": "🌦", "306": "🌧", "307": "🌧", "308": "🌧",
        "400": "🌨", "401": "❄️",
        "500": "🌫", "501": "🌫",
        "900": "❓", "999": "❓"
    }

    return icon_map.get(str(icon), "🌈")


# =========================
# 新增模块：蒸发空调控制算法
# =========================

def calc_wetbulb(temp, humidity):

    t = float(temp)
    rh = float(humidity)

    tw = (
        t * math.atan(0.151977 * (rh + 8.313659) ** 0.5)
        + math.atan(t + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )

    return tw


def evap_efficiency(temp, humidity):

    tw = calc_wetbulb(temp, humidity)
    potential = float(temp) - tw

    if potential >= 7:
        return "高"
    elif potential >= 4:
        return "中"
    else:
        return "低"


def fan_power_advice(temp, humidity):

    tw = calc_wetbulb(temp, humidity)
    potential = float(temp) - tw
    max_power = 35

    if float(temp) <= 10:
        pct = 30
    elif potential >= 7:
        pct = 90
    elif potential >= 4:
        pct = 70
    elif potential >= 2:
        pct = 50
    else:
        pct = 35

    kw = round(max_power * pct / 100, 1)

    return pct, kw


def water_ac_advice(temp, humidity, dew):

    temp = float(temp)
    humidity = float(humidity)
    dew = float(dew)

    efficiency = evap_efficiency(temp, humidity)
    pct, kw = fan_power_advice(temp, humidity)

    # ===== 冬季模式 =====
    if temp <= 10:

        if humidity >= 75:
            return (
                "风量：小（或关闭）\n"
                "水量：关\n"
                "外窗：小（或关闭）\n"
                "内窗：大\n"
                f"原因：外部湿度过高，蒸发加湿会导致湿度累积；风机功率建议：{pct}%（约{kw}kW）"
            )

        else:
            return (
                "风量：小\n"
                "水量：小\n"
                "外窗：小\n"
                "内窗：大\n"
                f"原因：冬季空气干燥，可利用余热循环加湿；风机功率建议：{pct}%（约{kw}kW）"
            )

    # ===== 高湿度保护 =====
    if humidity >= 80 or dew >= 26:
        return (
            "风量：大\n"
            "水量：关\n"
            "外窗：小\n"
            "内窗：大\n"
            f"原因：空气湿度过高，喷淋必须关闭防止结露；风机功率建议：{pct}%（约{kw}kW）"
        )

    # ===== 蒸发效率高 =====
    if efficiency == "高":
        return (
            "风量：高\n"
            "水量：高\n"
            "外窗：开\n"
            "内窗：小\n"
            f"原因：蒸发效率高，适合最大制冷；风机功率建议：{pct}%（约{kw}kW）"
        )

    # ===== 蒸发效率中 =====
    if efficiency == "中":
        return (
            "风量：高\n"
            "水量：中\n"
            "外窗：半开\n"
            "内窗：中\n"
            f"原因：蒸发效率一般；风机功率建议：{pct}%（约{kw}kW）"
        )

    # ===== 蒸发效率低 =====
    return (
        "风量：中\n"
        "水量：小\n"
        "外窗：开\n"
        "内窗：中\n"
        f"原因：蒸发效率较低；风机功率建议：{pct}%（约{kw}kW）"
    )

def floor_vent_advice(temp):

    temp = float(temp)

    if temp >= 30:
        return (
            "模式：排热(设备热量通过地排或管道排出)\n"
            "地排：开\n"
            "热风窗：开\n"
        )

    if temp <= 10:
        return (
            "模式：循环(热空气进入水帘房加湿后回送车间)\n"
            "地排：开\n"
            "热风窗：关\n"
        )

    return (
        "模式：通风排热（维持空气循环）\n"
        "地排：视车间温湿度情况开启\n"
    )


# =========================
# 消息生成
# =========================

def build_message(now_data, future_hours, alert_data, air_quality_data):
    now = now_data.get("now", {})
    icon = now.get("icon", "999")
    emoji = icon_to_emoji(icon)

    text = now.get("text", "未知")
    temp = now.get("temp", "?")
    humidity = now.get("humidity", "?")
    dew = now.get("dew", "?")

    air_now = air_quality_data.get("now", {})
    aqi_category = air_now.get("category", "未知")
    aqi = air_now.get("aqi", "N/A")

    lines = []

    # 实时天气
    lines.append("**如皋实时天气**")
    lines.append(f"- {text} {emoji} {temp}°C，相对湿度 {humidity}%")
    lines.append(f"- 露点 {dew}°C，空气质量 {aqi_category} AQI {aqi}")
    lines.append("------")

    # 未来4小时预报
    lines.append("🕖未来4小时预报")
    for h in future_hours:
        t = format_time_bj(h["fxTime"])
        lines.append(f"- {t}：{h['text']} | {h['temp']}°C，湿度 {h['humidity']}%")
    lines.append("------")

    # 天气预警
    alerts = alert_data.get("warning", [])
    if alerts:
        lines.append("🚨天气预警")
        for a in alerts:
            desc = a.get("text", "").replace('\n', ' ')
            lines.append(f"- {desc}")
        lines.append("------")
    
    else:
        lines.append("🌞无天气预警")
        lines.append("------")
    
    # 空调建议
    ac_advice = water_ac_advice(temp, humidity, dew)
    lines.append("💧水空调建议")
    advice_lines = ac_advice.split("\n")
    for line in advice_lines:
        lines.append(f"- {line}")
    lines.append("------")

    # 地排风建议
    floor_advice = floor_vent_advice(temp)
    lines.append("♨️地(热)排风建议")
    floor_lines = floor_advice.split("\n")
    for line in floor_lines:
        lines.append(f"- {line}")

    return "\n".join(lines)


def sign_request(timestamp, secret):

    string_to_sign = f"{timestamp}\n{secret}"

    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256
    ).digest()

    sign = quote_plus(base64.b64encode(hmac_code))

    return sign


def send_to_dingtalk(msg: str):

    url = DINGTALK_WEBHOOK
    headers = {"Content-Type": "application/json"}

    params = {}

    if DINGTALK_SECRET:

        ts = str(int(time.time() * 1000))

        params["timestamp"] = ts
        params["sign"] = sign_request(ts, DINGTALK_SECRET)

    body = {
        "msgtype": "markdown",
        "markdown": {
            "title": "如皋天气播报",
            "text": msg
        }
    }

    resp = requests.post(
        url,
        params=params,
        json=body,
        headers=headers,
        timeout=5
    )

    resp.raise_for_status()

    return resp.json()


def main():

    try:

        now_data = get_now_weather()
        hourly_data = get_hourly_forecast()
        alert_data = get_alerts()
        air_quality_data = get_air_quality()

        hourly = hourly_data.get("hourly", [])

        next_4h = filter_next_4h(hourly)

        if not next_4h:

            print("未获取到未来4小时预报")
            return

        message = build_message(
            now_data,
            next_4h,
            alert_data,
            air_quality_data
        )

        print("📤 模拟发送内容如下：\n")
        print(message)

        result = send_to_dingtalk(message)

        print("\n✅ 已发送，钉钉返回：", result)

    except Exception as e:

        print("❌ 发生错误：", e)


if __name__ == "__main__":
    main()
