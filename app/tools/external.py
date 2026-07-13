from __future__ import annotations

import logging

import httpx
from langchain.tools import tool

from app.cache.service import cache
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
    """搜索互联网以获取最新信息、新闻和网页来源。需要配置 TAVILY_API_KEY。"""

    if not settings.tavily_api_key:
        logger.warning("External tool is not configured tool=web_search")
        return {"error": "Web Search is not configured. Set TAVILY_API_KEY."}
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
            return {"error": "Web search returned an invalid response."}
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
        return {"error": "Web search failed. Check server logs."}


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
                return {"error": f"Location not found: {location}"}
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
        return {"error": "Weather lookup failed. Check server logs."}


@tool
def get_stock_quote(symbol: str) -> dict[str, object]:
    """查询股票代码的最新报价、涨跌幅和成交量。需要配置 ALPHA_VANTAGE_API_KEY。"""

    if not settings.alpha_vantage_api_key:
        logger.warning("External tool is not configured tool=get_stock_quote")
        return {"error": "Stock quote is not configured. Set ALPHA_VANTAGE_API_KEY."}
    ticker = symbol.strip().upper()
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
        quote = payload.get("Global Quote") or {}
        if not quote:
            logger.warning("Stock quote not found ticker=%s", ticker)
            return {
                "error": payload.get("Note")
                or payload.get("Information")
                or "Quote not found"
            }
        result = {
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
            "notice": "Market data may be delayed. This is not investment advice.",
            "cache_hit": False,
        }
        cache.set_json(key, result, ttl=STOCK_CACHE_TTL_SECONDS)
        logger.info("External tool completed tool=get_stock_quote ticker=%s", ticker)
        return result
    except Exception as exc:
        _log_failure("get_stock_quote", exc)
        return {"error": "Stock lookup failed. Check server logs."}
