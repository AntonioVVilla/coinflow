from pydantic import BaseModel


class Ticker(BaseModel):
    symbol: str
    last: float
    bid: float
    ask: float
    high: float
    low: float
    timestamp: int


class Balance(BaseModel):
    currency: str
    free: float
    used: float
    total: float


class OrderRequest(BaseModel):
    symbol: str
    side: str  # "buy" or "sell"
    order_type: str  # "market" or "limit"
    amount: float  # Crypto amount (base currency)
    price: float | None = None  # Required for limit orders
    cost: float | None = None  # USD quote cost (used for market buys on Coinbase)


class OrderResult(BaseModel):
    order_id: str = ""
    symbol: str
    side: str
    order_type: str
    amount: float = 0
    price: float = 0
    cost: float = 0
    fee: float = 0
    status: str = "filled"
