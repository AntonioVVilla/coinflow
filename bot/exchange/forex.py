import time
import logging
import aiohttp

logger = logging.getLogger(__name__)

# Cache: rate is fetched once per hour
_cache: dict = {"rate": None, "ts": 0}
_TTL = 3600  # 1 hour
_FALLBACK = 0.92  # fallback if API fails


async def get_usd_to_eur() -> float:
    """Get current USD to EUR conversion rate (cached)."""
    now = time.time()
    if _cache["rate"] is not None and (now - _cache["ts"]) < _TTL:
        return float(_cache["rate"])

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.frankfurter.app/latest?from=USD&to=EUR",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    rate = float(data.get("rates", {}).get("EUR", _FALLBACK))
                    _cache["rate"] = rate
                    _cache["ts"] = now
                    logger.info(f"USD/EUR rate updated: {rate}")
                    return rate
    except Exception as e:
        logger.warning(f"Failed to fetch USD/EUR rate: {e}")

    rate = _cache["rate"]
    return float(rate) if rate is not None else _FALLBACK
