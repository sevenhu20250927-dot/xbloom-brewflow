"""Estimate CNY token charges from an archived DeepSeek chat completion."""
from datetime import datetime
import json
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

# https://api-docs.deepseek.com/zh-cn/quick_start/pricing/
PRICE_DATE = "2026-11-26"
# Fen per million tokens off-peak: cache hit, cache miss, output. Peak is double.
FLASH = (2, 100, 400)
RATES = {"deepseek-flash": FLASH, "deepseek-v4-flash": FLASH,
         "deepseek-v4-flash-vision-exp": FLASH, "deepseek-v4-pro": (15, 450, 1350)}
# 国办发明电〔2025〕7号. Weekends always qualify for the provider's off-peak rate.
HOLIDAYS = {2026: ((101, 103), (215, 223), (404, 406), (501, 505),
                   (619, 621), (925, 927), (1001, 1007))}


def price_period(timestamp):
    if type(timestamp) is not int:
        return None
    try:
        local = datetime.fromtimestamp(timestamp, ZoneInfo("Asia/Shanghai"))
    except (ValueError, OverflowError, OSError):
        return None
    if local.weekday() >= 5 or not (9 <= local.hour < 12 or 14 <= local.hour < 18):
        return "off_peak"
    holidays = HOLIDAYS.get(local.year)
    if holidays is None:
        return None
    day = local.month * 100 + local.day
    return "off_peak" if any(start <= day <= end for start, end in holidays) else "peak"


def receipt(path, base_url):
    try:
        raw = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("usage"), dict):
        return None
    usage = raw["usage"]

    def count(value):
        return value if type(value) is int and value >= 0 else None

    prompt = count(usage.get("prompt_tokens"))
    output = count(usage.get("completion_tokens"))
    total = count(usage.get("total_tokens"))
    if total is None and prompt is not None and output is not None:
        total = prompt + output
    hit = count(usage.get("prompt_cache_hit_tokens"))
    details = usage.get("prompt_tokens_details")
    if hit is None and isinstance(details, dict):
        hit = count(details.get("cached_tokens"))
    miss = count(usage.get("prompt_cache_miss_tokens"))
    if prompt is not None:
        if hit is None and miss is not None and miss <= prompt:
            hit = prompt - miss
        if miss is None and hit is not None and hit <= prompt:
            miss = prompt - hit
    result = dict(created=count(raw.get("created")), prompt_tokens=prompt, completion_tokens=output, total_tokens=total,
                  cache_hit_tokens=hit, cache_miss_tokens=miss)
    if prompt is None or output is None or total != prompt + output:
        return result
    if hit is not None and miss is not None and hit + miss != prompt:
        return result
    model = raw.get("model")
    rates = RATES.get(model) if isinstance(model, str) else None
    if not rates or urlsplit(base_url or "").netloc.lower() not in ("api.deepseek.com", "api.deepseek.com:443"):
        return result
    if (hit is None) != (miss is None):
        return result
    hit_rate, miss_rate, out_rate = rates
    low_input = prompt * hit_rate if hit is None else hit * hit_rate + miss * miss_rate
    high_input = prompt * miss_rate if hit is None else low_input
    period = price_period(raw.get("created"))
    result.update(price_date=PRICE_DATE, period=period,
                  min_cny=(low_input + output * out_rate) * (2 if period == "peak" else 1) / 100_000_000,
                  max_cny=(high_input + output * out_rate) * (1 if period == "off_peak" else 2) / 100_000_000)
    return result
