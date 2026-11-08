"""OrderFlow configuration and environment loading module.

Reliably loads environment variables from backend/.env regardless of the current
working directory, while preserving existing environment variables set by the OS,
container runtime, or test runner.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent


def find_env_file(explicit_path: Path | str | None = None) -> Path | None:
    """Find the canonical .env file.
    
    Resolution order:
    1. Explicit path parameter if provided and exists.
    2. ORDERFLOW_ENV_FILE environment variable if set and exists.
    3. backend/.env (canonical backend configuration location).
    4. .env in the current working directory.
    """
    if explicit_path:
        p = Path(explicit_path).resolve()
        if p.is_file():
            return p

    env_var_path = os.getenv("ORDERFLOW_ENV_FILE")
    if env_var_path:
        p = Path(env_var_path).resolve()
        if p.is_file():
            return p

    backend_env = BACKEND_DIR / ".env"
    if backend_env.is_file():
        return backend_env

    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file():
        return cwd_env

    return None


def load_environment(
    env_file: Path | str | None = None,
    override: bool = False,
) -> Path | None:
    """Load environment variables into os.environ.
    
    By default override=False so that existing OS environment variables,
    container secrets, or CI variables are preserved.
    """
    target = find_env_file(env_file)
    if target:
        load_dotenv(dotenv_path=target, override=override)
        return target
    return None


def get_database_url() -> str | None:
    """Retrieve the configured database URL."""
    return os.getenv("DATABASE_URL")


def get_supabase_url() -> str | None:
    """Retrieve the configured Supabase project URL."""
    url = os.getenv("SUPABASE_URL")
    return url.rstrip("/") if url else None


def get_supabase_service_role_key() -> str | None:
    """Retrieve the Supabase service role key if available."""
    return os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")


def get_cors_origins() -> list[str]:
    """Retrieve allowed CORS origins as a list of strings."""
    raw = os.getenv("ORDERFLOW_CORS_ORIGINS", "http://localhost:5173")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def get_gemini_api_key() -> str | None:
    """Retrieve the Gemini API key if configured."""
    return os.getenv("GEMINI_API_KEY")


def get_gemini_model() -> str:
    """Retrieve the Gemini model name with default fallback."""
    return os.getenv("GEMINI_MODEL", "gemini-3.8-flash")


# Eagerly load environment on import
load_environment()

