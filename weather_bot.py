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
QWEATHER_API_KEY = os.getenv("QWEATHER_API_KEY", "ecf818ea29f1491faeee08f860ab8573")
LOCATION = os.getenv("LOCATION", "120.56,32.39")  # 江苏如皋坐标

DINGTALK_WEBHOOK = os.getenv(
    "DINGTALK_WEBHOOK",
    "https://oapi.dingtalk.com/robot/send?access_token=fc18ee89d0d862b9ce3e6a4071b396b8f41a3f103fd9a5620d45ba81c94c44da"
)
DINGTALK_SECRET = os.getenv(
    "DINGTALK_SECRET",
    "SECc6f568f3a5374e96f7bc191f832f7d7ef88326412a8883e5c60c14c132736e99"
)
# ---------------------

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
        "305": "🌦", "306": "🌧", "307": "🌧", "308": "🌧", "309": "🌦",
        "310": "🌧", "311": "🌧", "312": "🌧", "313": "🌧",
        "400": "🌨", "401": "❄️", "402": "❄️", "403": "❄️",
        "404": "🌨", "405": "🌨", "406": "🌨", "407": "🌨",
        "500": "🌫", "501": "🌫", "502": "🌁", "503": "🌁", "504": "🌫",
        "507": "🌫", "508": "🌫",
        "900": "❓", "999": "❓"
    }
    return icon_map.get(str(icon), "🌈")

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
    lines.append("如皋实时天气：")
    lines.append(f"{text} {emoji}{temp}°C，相对湿度{humidity}%，露点{dew}°C")
    lines.append(f"空气质量|{aqi_category}（AQI {aqi}）")
    lines.append("──────────")

    lines.append("🕖️未来4小时预报：")
    for h in future_hours:
        t = format_time_bj(h["fxTime"])
        lines.append(f"{t}-{h['text']}|{h['temp']}°C，湿度{h['humidity']}%")
    lines.append("──────────")

    alerts = alert_data.get("warning", [])
    if alerts:
        lines.append("🚨天气预警：")
        for a in alerts:
            desc = a.get("text", "").replace('\n', ' ')
            lines.append(desc)
    else:
        lines.append("🌞无天气预警")

    return "\n".join(lines)

def sign_request(timestamp, secret):
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(secret.encode("utf-8"),
                         string_to_sign.encode("utf-8"),
                         digestmod=hashlib.sha256).digest()
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

    resp = requests.post(url, params=params, json=body, headers=headers, timeout=5)
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
            print("未获取到未来 4 小时的预报。")
            return

        message = build_message(now_data, next_4h, alert_data, air_quality_data)
        print("📤 模拟发送内容如下：\n")
        print(message)

        result = send_to_dingtalk(message)
        print("\n✅ 已发送，钉钉返回：", result)

    except Exception as e:
        print("❌ 发生错误：", e)

if __name__ == "__main__":
    main()
