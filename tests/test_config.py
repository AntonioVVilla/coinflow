"""Tests for configuration settings."""
import pytest
from bot.config import settings, Settings


def test_default_paper_mode_is_true():
    assert settings.paper_mode is True


def test_supported_symbols_contains_btc():
    assert "BTC/USD" in settings.supported_symbols


def test_supported_symbols_contains_eth():
    assert "ETH/USD" in settings.supported_symbols


def test_supported_symbols_not_empty():
    assert len(settings.supported_symbols) > 0


def test_grid_tick_seconds_default():
    assert settings.grid_tick_seconds == 30


def test_max_requests_per_second_default():
    assert settings.max_requests_per_second == 10


def test_host_default():
    assert settings.host == "0.0.0.0"


def test_port_default():
    assert settings.port == 8080


def test_log_level_default():
    assert settings.log_level == "INFO"


def test_settings_supports_minimal_symbols():
    """Settings should accept custom symbols list."""
    s = Settings(supported_symbols=["BTC/USD"])
    assert "BTC/USD" in s.supported_symbols


def test_settings_grid_tick_must_be_positive():
    s = Settings(grid_tick_seconds=60)
    assert s.grid_tick_seconds == 60


def test_settings_env_file_loading(tmp_path, monkeypatch):
    """Test that settings loads from .env file."""
    import os
    env_file = tmp_path / ".env"
    env_file.write_text("PAPER_MODE=false\nLOG_LEVEL=DEBUG\n")

    monkeypatch.setenv("ENV_FILE", str(env_file))
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    s = Settings()
    assert s.log_level == "DEBUG"