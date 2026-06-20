"""Signed Binance USD-M Futures client for explicit live execution."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import time
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class SignedTransport(Protocol):
    def request_json(
        self,
        url: str,
        *,
        method: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> tuple[int, Any, dict[str, str]]:
        """Return status code, parsed JSON payload, and response headers."""


class UrllibSignedTransport:
    def request_json(
        self,
        url: str,
        *,
        method: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> tuple[int, Any, dict[str, str]]:
        request = Request(url, headers=dict(headers), method=method)
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL is caller configured.
                raw = response.read().decode("utf-8")
                return response.status, _parse_json(raw), dict(response.headers.items())
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            return exc.code, _parse_json(raw), dict(exc.headers.items())
        except URLError as exc:
            raise BinanceSignedError(
                endpoint="",
                params={},
                status_code=None,
                binance_code=None,
                binance_message=str(exc.reason),
                headers={},
            ) from exc


@dataclass(frozen=True)
class BinanceSignedError(Exception):
    endpoint: str
    params: dict[str, str]
    status_code: int | None
    binance_code: int | None
    binance_message: str
    headers: dict[str, str]

    def __str__(self) -> str:
        return f"{self.endpoint} failed: {self.binance_message}"


class BinanceFuturesSignedClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        api_secret: str,
        transport: SignedTransport | None = None,
        timeout: float = 10.0,
        recv_window: int = 5000,
        timestamp_ms=None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.transport = transport or UrllibSignedTransport()
        self.timeout = timeout
        self.recv_window = recv_window
        self.timestamp_ms = timestamp_ms or (lambda: int(time.time() * 1000))

    def change_margin_type(self, symbol: str, *, margin_type: str = "ISOLATED") -> dict[str, Any]:
        return self._signed_request(
            "POST",
            "/fapi/v1/marginType",
            {"symbol": _symbol(symbol), "marginType": margin_type.upper()},
        )

    def change_initial_leverage(self, symbol: str, *, leverage: int) -> dict[str, Any]:
        return self._signed_request(
            "POST",
            "/fapi/v1/leverage",
            {"symbol": _symbol(symbol), "leverage": str(leverage)},
        )

    def new_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        reduce_only: bool = False,
        position_side: str | None = None,
        new_client_order_id: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "symbol": _symbol(symbol),
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": _number(quantity),
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        if position_side:
            params["positionSide"] = position_side.upper()
        if new_client_order_id:
            params["newClientOrderId"] = new_client_order_id
        return self._signed_request("POST", "/fapi/v1/order", params)

    def new_algo_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        stop_price: float,
        close_position: bool = True,
        quantity: float | None = None,
        position_side: str | None = None,
        client_algo_id: str | None = None,
        working_type: str = "MARK_PRICE",
    ) -> dict[str, Any]:
        params = {
            "symbol": _symbol(symbol),
            "side": side.upper(),
            "algoType": "CONDITIONAL",
            "type": order_type.upper(),
            "triggerPrice": _number(stop_price),
            "workingType": working_type.upper(),
        }
        if position_side:
            params["positionSide"] = position_side.upper()
        if close_position:
            params["closePosition"] = "true"
        elif quantity is not None:
            params["quantity"] = _number(quantity)
        else:
            raise ValueError("quantity is required when close_position is false")
        if client_algo_id:
            params["clientAlgoId"] = client_algo_id
        return self._signed_request("POST", "/fapi/v1/algoOrder", params)

    def cancel_order(
        self,
        *,
        symbol: str,
        order_id: int | str | None = None,
        orig_client_order_id: str | None = None,
    ) -> dict[str, Any]:
        if order_id is None and not orig_client_order_id:
            raise ValueError("order_id or orig_client_order_id is required")
        params = {"symbol": _symbol(symbol)}
        if order_id is not None:
            params["orderId"] = str(order_id)
        if orig_client_order_id:
            params["origClientOrderId"] = orig_client_order_id
        return self._signed_request("DELETE", "/fapi/v1/order", params)

    def cancel_all_open_algo_orders(self, symbol: str) -> dict[str, Any]:
        return self._signed_request(
            "DELETE",
            "/fapi/v1/algoOpenOrders",
            {"symbol": _symbol(symbol)},
        )

    def test_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        position_side: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "symbol": _symbol(symbol),
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": _number(quantity),
        }
        if position_side:
            params["positionSide"] = position_side.upper()
        return self._signed_request(
            "POST",
            "/fapi/v1/order/test",
            params,
        )

    def account(self) -> dict[str, Any]:
        return self._signed_request("GET", "/fapi/v3/account", {})

    def open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"symbol": _symbol(symbol)} if symbol else {}
        payload = self._signed_request("GET", "/fapi/v1/openOrders", params)
        return payload if isinstance(payload, list) else [payload]

    def open_algo_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"symbol": _symbol(symbol)} if symbol else {}
        payload = self._signed_request("GET", "/fapi/v1/openAlgoOrders", params)
        return payload if isinstance(payload, list) else [payload]

    def position_risk(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"symbol": _symbol(symbol)} if symbol else {}
        payload = self._signed_request("GET", "/fapi/v2/positionRisk", params)
        return payload if isinstance(payload, list) else [payload]

    def user_trades(
        self,
        symbol: str,
        *,
        order_id: int | str | None = None,
        start_time: int | str | None = None,
        end_time: int | str | None = None,
        from_id: int | str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"symbol": _symbol(symbol), "limit": str(limit)}
        if order_id is not None:
            params["orderId"] = str(order_id)
        if start_time is not None:
            params["startTime"] = str(start_time)
        if end_time is not None:
            params["endTime"] = str(end_time)
        if from_id is not None:
            params["fromId"] = str(from_id)
        payload = self._signed_request("GET", "/fapi/v1/userTrades", params)
        return payload if isinstance(payload, list) else [payload]

    def _signed_request(
        self,
        method: str,
        endpoint: str,
        params: Mapping[str, str],
    ) -> Any:
        signed_params = {key: str(value) for key, value in params.items()}
        signed_params["recvWindow"] = str(self.recv_window)
        signed_params["timestamp"] = str(self.timestamp_ms())
        query = urlencode(signed_params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signed_params["signature"] = signature
        url = f"{self.base_url}{endpoint}?{urlencode(signed_params)}"
        status_code, payload, headers = self.transport.request_json(
            url,
            method=method,
            headers={"X-MBX-APIKEY": self.api_key},
            timeout=self.timeout,
        )
        if status_code < 200 or status_code >= 300:
            raise _error_from_payload(endpoint, signed_params, status_code, payload, headers)
        if isinstance(payload, dict):
            return dict(payload)
        return payload


def _symbol(value: str | None) -> str:
    if not value:
        raise ValueError("symbol is required")
    cleaned = value.strip().upper()
    if not cleaned:
        raise ValueError("symbol is required")
    return cleaned


def _number(value: float) -> str:
    return format(float(value), "f").rstrip("0").rstrip(".")


def _parse_json(raw: str) -> Any:
    if raw == "":
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"msg": raw}


def _error_from_payload(
    endpoint: str,
    params: dict[str, str],
    status_code: int,
    payload: Any,
    headers: dict[str, str],
) -> BinanceSignedError:
    code = payload.get("code") if isinstance(payload, dict) else None
    message = payload.get("msg") if isinstance(payload, dict) else None
    return BinanceSignedError(
        endpoint=endpoint,
        params={key: value for key, value in params.items() if key != "signature"},
        status_code=status_code,
        binance_code=code if isinstance(code, int) else None,
        binance_message=str(message or "Binance signed request failed"),
        headers=headers,
    )
