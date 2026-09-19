"""Pydantic schemas validating raw API payloads at the boundary.

Schemas describe the external wire format only; domain conversion belongs to
the parser layer.
"""

from pydantic import BaseModel, ConfigDict, model_validator


class ApiSchema(BaseModel):
    """Base schema that ignores unknown provider fields."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class BinanceAggTradeSchema(ApiSchema):
    """An aggregate trade from Binance ``/api/v3/aggTrades``."""

    a: int = 0
    p: str = "0"
    q: str = "0"
    T: int = 0
    m: bool = False


class MexcTradeSchema(ApiSchema):
    """A public trade from MEXC ``/api/v3/trades``.

    MEXC leaves ``id`` null on public trades, so the parser derives a
    deterministic identifier from the trade fields.
    """

    id: str | None = None
    price: str = "0"
    qty: str = "0"
    quoteQty: str = "0"
    time: int = 0
    isBuyerMaker: bool = False
    tradeType: str = ""


class CoinbaseTradeSchema(ApiSchema):
    """A public trade from Coinbase Exchange ``/products/{id}/trades``."""

    trade_id: int = 0
    side: str = ""
    size: str = "0"
    price: str = "0"
    time: str = ""


class KrakenPublicTradeSchema(ApiSchema):
    """A public trade row from Kraken ``/0/public/Trades``.

    Kraken returns each trade as a positional array; the before-validator
    maps that row onto named fields.
    """

    price: str = "0"
    volume: str = "0"
    time: float = 0.0
    side: str = ""
    order_type: str = ""
    misc: str = ""
    trade_id: int = 0

    @model_validator(mode="before")
    @classmethod
    def _from_row(cls, value: object) -> object:
        if isinstance(value, (list, tuple)) and len(value) >= 7:
            return {
                "price": value[0],
                "volume": value[1],
                "time": value[2],
                "side": value[3],
                "order_type": value[4],
                "misc": value[5],
                "trade_id": value[6],
            }
        return value


class BybitPublicTradeSchema(ApiSchema):
    """A public trade from Bybit ``/v5/market/recent-trade``."""

    execId: str = ""
    symbol: str = ""
    price: str = "0"
    size: str = "0"
    side: str = ""
    time: str = "0"


class OkxPublicTradeSchema(ApiSchema):
    """A public trade from OKX ``/api/v5/market/trades``."""

    tradeId: str = ""
    instId: str = ""
    px: str = "0"
    sz: str = "0"
    side: str = ""
    ts: str = "0"


class KucoinPublicTradeSchema(ApiSchema):
    """A public trade from KuCoin ``/api/v1/market/histories``."""

    sequence: str = ""
    tradeId: str = ""
    price: str = "0"
    size: str = "0"
    side: str = ""
    time: int = 0


class BitgetPublicTradeSchema(ApiSchema):
    """A public trade from Bitget ``/api/v2/spot/market/fills``."""

    tradeId: str = ""
    symbol: str = ""
    side: str = ""
    price: str = "0"
    size: str = "0"
    ts: str = "0"


class GeminiPublicTradeSchema(ApiSchema):
    """A public trade from Gemini ``/v1/trades/{symbol}``."""

    tid: int = 0
    price: str = "0"
    amount: str = "0"
    type: str = ""
    timestampms: int = 0
