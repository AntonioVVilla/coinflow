"""Helpers for writing log records safely.

CodeQL flags `logger.info(f"... {user_value} ...")` as py/log-injection when
`user_value` can originate from user input (HTTP body, exchange payload,
Telegram command, etc.). A malicious value containing newlines would forge
additional log lines and confuse downstream log analysis.

`safe` strips CR/LF and other control characters before interpolation; use it
to wrap any value that is not known to be trusted.
"""
from __future__ import annotations

_CTRL = {chr(i) for i in range(0x00, 0x20)} - {"\t"}
_CTRL.add("\x7f")


def safe(value: object, max_len: int = 200) -> str:
    """Return `value` as a single-line string with control chars stripped."""
    text = str(value)
    cleaned = "".join(ch for ch in text if ch not in _CTRL)
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "..."
    return cleaned
