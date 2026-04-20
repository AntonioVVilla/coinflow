"""Daily summary: recaps the last 24h and sends to Telegram + Email."""
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, desc
from bot.database import async_session
from bot.models import Trade, PortfolioSnapshot
from bot.engine.runner import get_exchange_client, get_all_statuses
from bot.notifications.config import load_channel
from bot.notifications.telegram_notify import send_telegram_with
from bot.notifications.email_notify import send_email_test
from bot.exchange.forex import get_usd_to_eur
from bot.config import settings

logger = logging.getLogger(__name__)


async def build_daily_summary() -> dict:
    """Compile a summary of the last 24 hours."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)

    client = get_exchange_client()

    # Current balances and portfolio value
    current_total = 0
    balances_map = {}
    if client:
        try:
            bals = await client.fetch_balance()
            balances_map = {b.currency: b.total for b in bals if b.total > 0}

            prices = {}
            for sym in settings.supported_symbols:
                try:
                    t = await client.fetch_ticker(sym)
                    prices[sym] = t.last
                except Exception as ticker_err:
                    logger.debug(f"Ticker fetch failed for {sym}: {ticker_err}")

            eur_rate = await get_usd_to_eur()
            usd_per_eur = (1 / eur_rate) if eur_rate else 1.18
            for cur, amt in balances_map.items():
                if cur == "USD":
                    current_total += amt
                elif cur == "USDC":
                    current_total += amt
                elif cur == "EUR":
                    current_total += amt * usd_per_eur
                else:
                    for q in ("USD", "USDC"):
                        if f"{cur}/{q}" in prices:
                            current_total += amt * prices[f"{cur}/{q}"]
                            break
                    else:
                        if f"{cur}/EUR" in prices:
                            current_total += amt * prices[f"{cur}/EUR"] * usd_per_eur
        except Exception as e:
            logger.error(f"Summary balance error: {e}")

    # Portfolio change (compare with 24h ago snapshot)
    yesterday_total = None
    async with async_session() as session:
        snapshot_result = await session.execute(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.snapshot_at <= since)
            .order_by(desc(PortfolioSnapshot.snapshot_at))
            .limit(1)
        )
        snapshot_row = snapshot_result.scalar_one_or_none()
        if snapshot_row:
            yesterday_total = snapshot_row.total_usd

    change_usd = current_total - yesterday_total if yesterday_total else 0
    change_pct = (change_usd / yesterday_total * 100) if yesterday_total else 0

    # Trades in last 24h
    async with async_session() as session:
        trades_result = await session.execute(
            select(Trade).where(Trade.created_at >= since).order_by(desc(Trade.created_at))
        )
        trades = list(trades_result.scalars().all())

        # Aggregates
        buys = [t for t in trades if t.side == "buy"]
        sells = [t for t in trades if t.side == "sell"]
        buy_volume = sum(t.cost for t in buys)
        sell_volume = sum(t.cost for t in sells)
        fees = sum(t.fee for t in trades)

        # By strategy
        by_strategy: dict[str, dict[str, float]] = {}
        for t in trades:
            if t.strategy not in by_strategy:
                by_strategy[t.strategy] = {"count": 0, "buys": 0, "sells": 0, "volume": 0.0}
            by_strategy[t.strategy]["count"] += 1
            by_strategy[t.strategy]["volume"] += t.cost
            if t.side == "buy":
                by_strategy[t.strategy]["buys"] += 1
            else:
                by_strategy[t.strategy]["sells"] += 1

    active = get_all_statuses()

    return {
        "date": now.date().isoformat(),
        "current_total_usd": round(current_total, 2),
        "yesterday_total_usd": round(yesterday_total, 2) if yesterday_total else None,
        "change_usd": round(change_usd, 2),
        "change_pct": round(change_pct, 2),
        "balances": {k: round(v, 8) for k, v in balances_map.items()},
        "trades_count": len(trades),
        "buys_count": len(buys),
        "sells_count": len(sells),
        "buy_volume": round(buy_volume, 2),
        "sell_volume": round(sell_volume, 2),
        "realized_pnl_24h": round(sell_volume - buy_volume, 2),
        "fees_24h": round(fees, 4),
        "by_strategy": by_strategy,
        "active_strategies": list(active.keys()),
        "recent_trades": [
            {
                "time": t.created_at.strftime("%H:%M"),
                "side": t.side,
                "amount": t.amount,
                "symbol": t.symbol,
                "price": t.price,
                "cost": round(t.cost, 2),
                "strategy": t.strategy,
            }
            for t in trades[:10]
        ],
    }


def format_telegram_summary(s: dict) -> str:
    arrow = "📈" if s["change_usd"] > 0 else ("📉" if s["change_usd"] < 0 else "➡️")
    change_sign = "+" if s["change_usd"] > 0 else ""

    lines = [
        f"*📊 Resumen diario - {s['date']}*",
        "",
        f"{arrow} *Portfolio:* ${s['current_total_usd']:,.2f}",
    ]
    if s.get("yesterday_total_usd"):
        lines.append(f"   Ayer: ${s['yesterday_total_usd']:,.2f}  ({change_sign}${s['change_usd']:,.2f} / {change_sign}{s['change_pct']:.2f}%)")

    lines.append("")
    lines.append(f"*📜 Operaciones (24h):* {s['trades_count']}")
    if s["trades_count"] > 0:
        lines.append(f"  🟢 Compras: {s['buys_count']} (${s['buy_volume']:,.2f})")
        lines.append(f"  🔴 Ventas: {s['sells_count']} (${s['sell_volume']:,.2f})")
        lines.append(f"  💸 Fees: ${s['fees_24h']:,.4f}")

        if s["by_strategy"]:
            lines.append("")
            lines.append("*Por estrategia:*")
            for name, stats in s["by_strategy"].items():
                lines.append(f"  • `{name}`: {stats['count']} trades, ${stats['volume']:,.2f}")

    if s["active_strategies"]:
        lines.append("")
        lines.append(f"*🟢 Activas:* {', '.join(s['active_strategies'])}")

    if s["balances"]:
        lines.append("")
        lines.append("*💰 Balances:*")
        for cur, amt in sorted(s["balances"].items()):
            if amt > 0.0001:
                lines.append(f"  {cur}: {amt:.8f}")

    return "\n".join(lines)


def format_email_summary(s: dict) -> tuple[str, str]:
    """Returns (subject, body)."""
    arrow = "UP" if s["change_usd"] > 0 else ("DOWN" if s["change_usd"] < 0 else "FLAT")
    change_sign = "+" if s["change_usd"] > 0 else ""

    subject = f"CryptoBot Resumen {s['date']} - {arrow} {change_sign}${s['change_usd']:,.2f} ({change_sign}{s['change_pct']:.2f}%)"

    lines = [
        f"Resumen diario de CryptoBot - {s['date']}",
        "=" * 50, "",
        f"Portfolio total: ${s['current_total_usd']:,.2f}",
    ]
    if s.get("yesterday_total_usd"):
        lines.append(f"Ayer:            ${s['yesterday_total_usd']:,.2f}")
        lines.append(f"Cambio:          {change_sign}${s['change_usd']:,.2f} ({change_sign}{s['change_pct']:.2f}%)")

    lines += ["", "OPERACIONES (ultimas 24h)", "-" * 30, f"Total: {s['trades_count']}"]
    if s["trades_count"] > 0:
        lines.append(f"  Compras: {s['buys_count']}  (${s['buy_volume']:,.2f})")
        lines.append(f"  Ventas:  {s['sells_count']}  (${s['sell_volume']:,.2f})")
        lines.append(f"  Fees:    ${s['fees_24h']:,.4f}")
        lines.append(f"  P&L realizado 24h: ${s['realized_pnl_24h']:+,.2f}")

    if s["by_strategy"]:
        lines.append("")
        lines.append("POR ESTRATEGIA")
        for name, stats in s["by_strategy"].items():
            lines.append(f"  {name}: {stats['count']} trades, ${stats['volume']:,.2f}")

    if s["balances"]:
        lines.append("")
        lines.append("BALANCES")
        for cur, amt in sorted(s["balances"].items()):
            if amt > 0.0001:
                lines.append(f"  {cur}: {amt:.8f}")

    if s["recent_trades"]:
        lines.append("")
        lines.append("TRADES RECIENTES")
        for t in s["recent_trades"]:
            lines.append(
                f"  {t['time']} {t['side'].upper():4s} {t['amount']:.8f} {t['symbol']} "
                f"@ ${t['price']:,.2f} = ${t['cost']:,.2f}  ({t['strategy']})"
            )

    return subject, "\n".join(lines)


async def send_daily_summary():
    """Called by scheduler once per day."""
    try:
        summary = await build_daily_summary()
        logger.info(f"Daily summary: {summary['trades_count']} trades, change ${summary['change_usd']}")

        tg = await load_channel("telegram")
        if tg.get("enabled") and tg.get("bot_token") and tg.get("chat_id"):
            msg = format_telegram_summary(summary)
            await send_telegram_with(tg["bot_token"], tg["chat_id"], msg)

        email = await load_channel("email")
        if email.get("enabled") and email.get("smtp_host") and email.get("email_to"):
            subject, body = format_email_summary(summary)
            await send_email_test(email, subject, body)

    except Exception as e:
        logger.error(f"Daily summary failed: {e}")
