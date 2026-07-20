from __future__ import annotations

import logging

import httpx
from langchain.tools import tool

from app.cache.service import cache
from app.core.admin_contact import append_admin_contact
from app.core.config import get_settings
from app.core.constants import (
    STOCK_CACHE_TTL_SECONDS,
    WEATHER_CACHE_TTL_SECONDS,
    WEB_SEARCH_CACHE_TTL_SECONDS,
)
from app.core.types import JsonObject
from app.tracing.service import safe_json

settings = get_settings()
logger = logging.getLogger(__name__)

STOCK_SYMBOL_ALIASES: dict[str, tuple[str, str]] = {
    "标普500": ("SPY", "标普500 ETF（SPY，跟踪标普500指数）"),
    "标准普尔500": ("SPY", "标普500 ETF（SPY，跟踪标普500指数）"),
    "sp500": ("SPY", "标普500 ETF（SPY，跟踪标普500指数）"),
    "sandp500": ("SPY", "标普500 ETF（SPY，跟踪标普500指数）"),
    "纳斯达克100": ("QQQ", "纳斯达克100 ETF（QQQ）"),
    "纳指100": ("QQQ", "纳斯达克100 ETF（QQQ）"),
    "nasdaq100": ("QQQ", "纳斯达克100 ETF（QQQ）"),
    "纳斯达克": ("QQQ", "纳斯达克100 ETF（QQQ）"),
    "纳指": ("QQQ", "纳斯达克100 ETF（QQQ）"),
    "道琼斯": ("DIA", "道琼斯工业平均指数 ETF（DIA）"),
    "道指": ("DIA", "道琼斯工业平均指数 ETF（DIA）"),
    "dowjones": ("DIA", "道琼斯工业平均指数 ETF（DIA）"),
    "苹果": ("AAPL", "苹果（AAPL）"),
    "微软": ("MSFT", "微软（MSFT）"),
    "英伟达": ("NVDA", "英伟达（NVDA）"),
    "特斯拉": ("TSLA", "特斯拉（TSLA）"),
    "亚马逊": ("AMZN", "亚马逊（AMZN）"),
    "谷歌": ("GOOGL", "Alphabet（GOOGL）"),
    "meta": ("META", "Meta（META）"),
}


def _compact_symbol_text(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _resolve_stock_symbol(symbol: str) -> tuple[str, str, str]:
    requested = symbol.strip()
    compact = _compact_symbol_text(requested)
    for alias, resolved in STOCK_SYMBOL_ALIASES.items():
        if alias in compact:
            ticker, display_name = resolved
            return ticker, display_name, requested

    ticker = requested.removeprefix("$").strip().upper().replace(" ", "")
    return ticker, ticker, requested


def _log_failure(tool_name: str, exc: Exception) -> None:
    status_code = (
        exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    )
    logger.warning(
        "External tool failed tool=%s error=%s status=%s",
        tool_name,
        type(exc).__name__,
        status_code,
    )


@tool
def web_search(query: str, max_results: int = 5) -> dict[str, object]:
    """搜索互联网以获取最新信息、新闻和网页来源。需要管理员配置联网搜索服务。"""

    if not settings.tavily_api_key:
        logger.warning("External tool is not configured tool=web_search")
        return {
            "error": append_admin_contact(
                "网页搜索尚未配置，请联系管理员配置联网搜索服务。"
            )
        }
    limit = max(1, min(max_results, 10))
    key = f"tool:web:{cache.digest(query, limit)}"
    if isinstance(cached := cache.get_json(key), dict):
        logger.debug("External tool cache hit tool=web_search")
        return {**cached, "cache_hit": True}

    try:
        with httpx.Client(timeout=settings.external_api_timeout) as client:
            response = client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": limit,
                    "include_answer": True,
                },
            )
            response.raise_for_status()
            payload = safe_json(response.json())
        if not isinstance(payload, dict):
            return {"error": "网页搜索服务返回异常。"}
        raw_results = payload.get("results")
        result: JsonObject = {
            "query": query,
            "answer": payload.get("answer"),
            "results": [
                {
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "content": item.get("content"),
                    "score": item.get("score"),
                }
                for item in (raw_results if isinstance(raw_results, list) else [])[
                    :limit
                ]
                if isinstance(item, dict)
            ],
            "cache_hit": False,
        }
        cache.set_json(key, result, ttl=WEB_SEARCH_CACHE_TTL_SECONDS)
        logger.info(
            "External tool completed tool=web_search results=%s",
            len(result["results"]),
        )
        return result
    except Exception as exc:
        _log_failure("web_search", exc)
        return {"error": "网页搜索失败，请稍后重试。"}


@tool
def get_weather(location: str, forecast_days: int = 3) -> dict[str, object]:
    """查询全球城市或地区的当前天气与未来几天天气预报。"""

    days = max(1, min(forecast_days, 7))
    key = f"tool:weather:{cache.digest(location, days)}"
    if isinstance(cached := cache.get_json(key), dict):
        logger.debug("External tool cache hit tool=get_weather")
        return {**cached, "cache_hit": True}

    try:
        with httpx.Client(timeout=settings.external_api_timeout) as client:
            geocoding = client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={
                    "name": location,
                    "count": 1,
                    "language": "zh",
                    "format": "json",
                },
            )
            geocoding.raise_for_status()
            places = geocoding.json().get("results") or []
            if not places:
                return {"error": f"未找到地点：{location}"}
            place = places[0]
            forecast = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "forecast_days": days,
                    "timezone": "auto",
                },
            )
            forecast.raise_for_status()
            data = forecast.json()
        daily = data.get("daily", {})
        result = {
            "location": {
                "name": place.get("name"),
                "admin1": place.get("admin1"),
                "country": place.get("country"),
                "timezone": data.get("timezone"),
            },
            "current": data.get("current", {}),
            "daily": [
                {
                    "date": date,
                    "weather_code": daily.get("weather_code", [None] * days)[index],
                    "temperature_max_c": daily.get("temperature_2m_max", [None] * days)[
                        index
                    ],
                    "temperature_min_c": daily.get("temperature_2m_min", [None] * days)[
                        index
                    ],
                    "precipitation_probability_max": daily.get(
                        "precipitation_probability_max", [None] * days
                    )[index],
                }
                for index, date in enumerate(daily.get("time", []))
            ],
            "source": "Open-Meteo",
            "cache_hit": False,
        }
        cache.set_json(key, result, ttl=WEATHER_CACHE_TTL_SECONDS)
        logger.info("External tool completed tool=get_weather")
        return result
    except Exception as exc:
        _log_failure("get_weather", exc)
        return {"error": "天气查询失败，请稍后重试。"}


@tool
def get_stock_quote(symbol: str) -> dict[str, object]:
    """查询股票、ETF 或常见指数代理的最新报价。可传股票代码，也可传常见中文名称。"""

    if not settings.alpha_vantage_api_key:
        logger.warning("External tool is not configured tool=get_stock_quote")
        return {"error": append_admin_contact("股票行情服务尚未配置，请联系管理员。")}
    ticker, display_name, requested_symbol = _resolve_stock_symbol(symbol)
    if not ticker:
        return {"error": "请提供要查询的股票代码或名称。"}
    key = f"tool:stock:{cache.digest(ticker)}"
    if isinstance(cached := cache.get_json(key), dict):
        logger.debug("External tool cache hit tool=get_stock_quote ticker=%s", ticker)
        return {**cached, "cache_hit": True}

    try:
        with httpx.Client(timeout=settings.external_api_timeout) as client:
            response = client.get(
                "https://www.alphavantage.co/query",
                params={
                    "function": "GLOBAL_QUOTE",
                    "symbol": ticker,
                    "apikey": settings.alpha_vantage_api_key,
                },
            )
            response.raise_for_status()
            payload = response.json()
        service_notice = payload.get("Note") or payload.get("Information")
        if service_notice:
            logger.warning("Stock quote service notice ticker=%s", ticker)
            return {
                "requested_symbol": requested_symbol,
                "resolved_symbol": ticker,
                "display_name": display_name,
                "source": "Alpha Vantage",
                "error": "股票行情服务暂时不可用或达到调用频率限制，请稍后重试。",
            }
        if payload.get("Error Message"):
            logger.warning("Stock quote invalid ticker=%s", ticker)
            return {
                "requested_symbol": requested_symbol,
                "resolved_symbol": ticker,
                "display_name": display_name,
                "source": "Alpha Vantage",
                "error": f"股票代码无效或服务无法识别：{requested_symbol}",
            }
        quote = payload.get("Global Quote") or {}
        if not quote:
            logger.warning("Stock quote not found ticker=%s", ticker)
            return {
                "requested_symbol": requested_symbol,
                "resolved_symbol": ticker,
                "display_name": display_name,
                "source": "Alpha Vantage",
                "error": f"未找到股票行情：{requested_symbol}（已尝试代码 {ticker}）",
            }
        result = {
            "requested_symbol": requested_symbol,
            "resolved_symbol": ticker,
            "display_name": display_name,
            "symbol": quote.get("01. symbol", ticker),
            "open": quote.get("02. open"),
            "high": quote.get("03. high"),
            "low": quote.get("04. low"),
            "price": quote.get("05. price"),
            "volume": quote.get("06. volume"),
            "latest_trading_day": quote.get("07. latest trading day"),
            "previous_close": quote.get("08. previous close"),
            "change": quote.get("09. change"),
            "change_percent": quote.get("10. change percent"),
            "source": "Alpha Vantage",
            "notice": "行情数据可能存在延迟，不构成投资建议。",
            "cache_hit": False,
        }
        cache.set_json(key, result, ttl=STOCK_CACHE_TTL_SECONDS)
        logger.info("External tool completed tool=get_stock_quote ticker=%s", ticker)
        return result
    except Exception as exc:
        _log_failure("get_stock_quote", exc)
        return {"error": "股票行情查询失败，请稍后重试。"}
