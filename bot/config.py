from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # App
    paper_mode: bool = True
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8080
    data_dir: Path = Path("data")

    # Database
    database_url: str = "sqlite+aiosqlite:///data/bot.db"

    # Encryption
    encryption_key: str = ""

    # Telegram (optional)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Email (optional)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    email_to: str = ""

    # Trading defaults - pairs the UI can select from.
    # Each base asset listed with multiple quote currencies for flexibility.
    supported_symbols: list[str] = [
        # Major pairs
        "BTC/USD", "BTC/USDC", "BTC/EUR",
        "ETH/USD", "ETH/USDC", "ETH/EUR",
        # Altcoins L1/L2
        "SOL/USD", "SOL/USDC", "SOL/EUR",
        "AVAX/USD", "AVAX/USDC", "AVAX/EUR",
        "DOT/USD", "DOT/USDC", "DOT/EUR",
        "ADA/USD", "ADA/USDC", "ADA/EUR",
        "MATIC/USD", "MATIC/USDC",
        # Other popular
        "LINK/USD", "LINK/USDC", "LINK/EUR",
        "ATOM/USD", "ATOM/USDC",
        "XRP/USD", "XRP/USDC", "XRP/EUR",
        "DOGE/USD", "DOGE/USDC",
        "LTC/USD", "LTC/USDC", "LTC/EUR",
    ]
    grid_tick_seconds: int = 30
    max_requests_per_second: int = 10

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
