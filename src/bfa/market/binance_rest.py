"""Dependency-free public REST client for Binance USD-M futures market data."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bfa.market.models import MarketDataResponse


class RestTransport(Protocol):
    def get_json(self, url: str, *, timeout: float) -> tuple[int, Any, dict[str, str]]:
        """Return status code, parsed JSON payload, and response headers."""


class UrllibRestTransport:
    def get_json(self, url: str, *, timeout: float) -> tuple[int, Any, dict[str, str]]:
        request = Request(url, method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL is caller configured.
                raw = response.read().decode("utf-8")
                return response.status, json.loads(raw), dict(response.headers.items())
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            payload: Any
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"msg": raw}
            return exc.code, payload, dict(exc.headers.items())
        except URLError as exc:
            raise BinanceMarketDataError(
                endpoint="",
                params={},
                status_code=None,
                binance_code=None,
                binance_message=str(exc.reason),
                headers={},
            ) from exc


@dataclass(frozen=True)
class BinanceMarketDataError(Exception):
    endpoint: str
    params: dict[str, str]
    status_code: int | None
    binance_code: int | None
    binance_message: str
    headers: dict[str, str]

    @property
    def request_weight(self) -> str | None:
        for key, value in self.headers.items():
            if key.upper().startswith("X-MBX-USED-WEIGHT"):
                return value
        return None

    def __str__(self) -> str:
        detail = self.binance_message or "Binance market data request failed"
        return f"{self.endpoint} failed: {detail}"


class BinanceFuturesRestClient:
    def __init__(
        self,
        *,
        base_url: str,
        transport: RestTransport | None = None,
        timeout: float = 10.0,
        min_request_interval_seconds: float = 0.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport or UrllibRestTransport()
        self.timeout = timeout
        self.min_request_interval_seconds = min_request_interval_seconds
        self._last_request_at: float | None = None

    def exchange_info(self) -> MarketDataResponse:
        return self._get("/fapi/v1/exchangeInfo")

    def ticker_24hr(self, symbol: str) -> MarketDataResponse:
        return self._get(
            "/fapi/v1/ticker/24hr",
            {"symbol": _normalize_symbol(symbol)},
        )

    def klines(self, symbol: str, *, interval: str, limit: int = 30) -> MarketDataResponse:
        return self._get(
            "/fapi/v1/klines",
            {
                "symbol": _normalize_symbol(symbol),
                "interval": _require_text("interval", interval),
                "limit": str(_validate_limit(limit)),
            },
        )

    def funding_rate(self, symbol: str, *, limit: int = 20) -> MarketDataResponse:
        return self._get(
            "/fapi/v1/fundingRate",
            {
                "symbol": _normalize_symbol(symbol),
                "limit": str(_validate_limit(limit)),
            },
        )

    def open_interest(self, symbol: str) -> MarketDataResponse:
        return self._get(
            "/fapi/v1/openInterest",
            {"symbol": _normalize_symbol(symbol)},
        )

    def _get(self, endpoint: str, params: dict[str, str] | None = None) -> MarketDataResponse:
        request_params = {} if params is None else dict(params)
        self._pace()
        status_code, payload, headers = self.transport.get_json(
            self._build_url(endpoint, request_params),
            timeout=self.timeout,
        )
        if status_code < 200 or status_code >= 300:
            raise _error_from_payload(endpoint, request_params, status_code, payload, headers)
        return MarketDataResponse(
            endpoint=endpoint,
            params=request_params,
            payload=payload,
            status_code=status_code,
            headers=headers,
        )

    def _build_url(self, endpoint: str, params: dict[str, str]) -> str:
        query = urlencode(params)
        if query:
            return f"{self.base_url}{endpoint}?{query}"
        return f"{self.base_url}{endpoint}"

    def _pace(self) -> None:
        if self.min_request_interval_seconds <= 0:
            return
        now = time.monotonic()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            remaining = self.min_request_interval_seconds - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()


def _normalize_symbol(symbol: str) -> str:
    return _require_text("symbol", symbol).upper()


def _require_text(name: str, value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{name} is required")
    return cleaned


def _validate_limit(limit: int) -> int:
    if limit <= 0:
        raise ValueError("limit must be positive")
    return limit


def _error_from_payload(
    endpoint: str,
    params: dict[str, str],
    status_code: int,
    payload: Any,
    headers: dict[str, str],
) -> BinanceMarketDataError:
    code = payload.get("code") if isinstance(payload, dict) else None
    message = payload.get("msg") if isinstance(payload, dict) else None
    return BinanceMarketDataError(
        endpoint=endpoint,
        params=params,
        status_code=status_code,
        binance_code=code if isinstance(code, int) else None,
        binance_message=str(message or "Binance market data request failed"),
        headers=headers,
    )
