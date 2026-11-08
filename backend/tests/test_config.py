"""Unit tests for OrderFlow configuration and environment loading module."""

import os
from pathlib import Path
import pytest
from sqlalchemy.engine import Engine

from app import config
from app import database


def test_find_env_file_finds_backend_env(monkeypatch, tmp_path):
    """find_env_file should locate backend/.env even when working directory is elsewhere."""
    monkeypatch.delenv("ORDERFLOW_ENV_FILE", raising=False)
    # Change working directory to a temporary directory outside the project
    monkeypatch.chdir(tmp_path)
    found = config.find_env_file()
    assert found is not None
    assert found.name == ".env"
    assert found == config.BACKEND_DIR / ".env"


def test_find_env_file_explicit_path(monkeypatch, tmp_path):
    """find_env_file should respect explicit path parameter."""
    monkeypatch.delenv("ORDERFLOW_ENV_FILE", raising=False)
    custom_env = tmp_path / "custom.env"
    custom_env.write_text("DATABASE_URL=sqlite:///:memory:\n")
    found = config.find_env_file(explicit_path=custom_env)
    assert found == custom_env.resolve()


def test_find_env_file_env_var_override(monkeypatch, tmp_path):
    """find_env_file should respect ORDERFLOW_ENV_FILE environment variable."""
    custom_env = tmp_path / "var.env"
    custom_env.write_text("DATABASE_URL=sqlite:///:memory:\n")
    monkeypatch.setenv("ORDERFLOW_ENV_FILE", str(custom_env))
    found = config.find_env_file()
    assert found == custom_env.resolve()


def test_load_environment_preserves_existing_vars(monkeypatch, tmp_path):
    """load_environment with override=False must not overwrite existing environment variables."""
    custom_env = tmp_path / "preserve.env"
    custom_env.write_text("TEST_VAR_CONFIG=from_file\n")
    monkeypatch.setenv("TEST_VAR_CONFIG", "from_os")

    config.load_environment(env_file=custom_env, override=False)
    assert os.getenv("TEST_VAR_CONFIG") == "from_os"


def test_load_environment_override_true(monkeypatch, tmp_path):
    """load_environment with override=True should update existing variables."""
    custom_env = tmp_path / "override.env"
    custom_env.write_text("TEST_VAR_CONFIG=from_file\n")
    monkeypatch.setenv("TEST_VAR_CONFIG", "from_os")

    config.load_environment(env_file=custom_env, override=True)
    assert os.getenv("TEST_VAR_CONFIG") == "from_file"


def test_get_cors_origins(monkeypatch):
    """get_cors_origins should split by comma, strip whitespace, and filter empty strings."""
    monkeypatch.setenv(
        "ORDERFLOW_CORS_ORIGINS",
        " http://localhost:5173 , http://127.0.0.1:5173 , , http://kirana.store ",
    )
    origins = config.get_cors_origins()
    assert origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://kirana.store",
    ]


def test_get_cors_origins_default(monkeypatch):
    """get_cors_origins should return default frontend origin when unset."""
    monkeypatch.delenv("ORDERFLOW_CORS_ORIGINS", raising=False)
    assert config.get_cors_origins() == ["http://localhost:5173"]


def test_get_database_url(monkeypatch):
    """get_database_url should return DATABASE_URL from environment."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5433/db")
    assert config.get_database_url() == "postgresql+psycopg://user:pass@localhost:5433/db"


def test_get_supabase_url_strips_trailing_slash(monkeypatch):
    """get_supabase_url should return normalized URL without trailing slash."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co/")
    assert config.get_supabase_url() == "https://example.supabase.co"

    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert config.get_supabase_url() is None


def test_get_supabase_service_role_key(monkeypatch):
    """get_supabase_service_role_key should check primary and fallback variable names."""
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert config.get_supabase_service_role_key() is None

    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "fallback-key")
    assert config.get_supabase_service_role_key() == "fallback-key"

    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "primary-key")
    assert config.get_supabase_service_role_key() == "primary-key"


def test_get_gemini_api_key(monkeypatch):
    """get_gemini_api_key should return configured key or None."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert config.get_gemini_api_key() is None

    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    assert config.get_gemini_api_key() == "test-gemini-key"


def test_get_gemini_model_default(monkeypatch):
    """get_gemini_model should return default model when unset."""
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert config.get_gemini_model() == "gemini-3.8-flash"

    monkeypatch.setenv("GEMINI_MODEL", "custom-model")
    assert config.get_gemini_model() == "custom-model"


def test_get_engine_missing_database_url_raises_runtime_error(monkeypatch):
    """get_engine must raise RuntimeError with helpful guidance when DATABASE_URL is missing."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database.get_engine.cache_clear()

    with pytest.raises(RuntimeError) as exc_info:
        database.get_engine()

    assert "DATABASE_URL must be configured" in str(exc_info.value)
    database.get_engine.cache_clear()


def test_get_engine_creates_engine_when_database_url_is_set(monkeypatch):
    """get_engine should create an Engine instance when DATABASE_URL is present."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    database.get_engine.cache_clear()

    engine = database.get_engine()
    assert isinstance(engine, Engine)
    database.get_engine.cache_clear()
