"""Configuration. Everything comes from environment variables so the same
image can serve different clients by changing only the .env file."""

import os


def _bool(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).strip().lower() in ("1", "true", "yes", "on")


def _list(key: str, default: str = "") -> list:
    return [x.strip() for x in os.getenv(key, default).split(",") if x.strip()]


class Settings:
    # --- identity ---------------------------------------------------------
    CLIENT_NAME = os.getenv("CLIENT_NAME", "client")

    # --- WooCommerce database (READ-ONLY user, please) --------------------
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "reco_read")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "wordpress")
    DB_SOCKET = os.getenv("DB_SOCKET", "")  # Unix socket path, overrides TCP
    WP_PREFIX = os.getenv("WP_PREFIX", "wp_")

    # --- refresh ----------------------------------------------------------
    # Product text changes rarely; the full rebuild is expensive-ish.
    REBUILD_MINUTES = int(os.getenv("REBUILD_MINUTES", "60"))
    # Price and stock change constantly; fetched per request for the handful
    # of products actually returned. Set 0 to disable (uses cached values).
    LIVE_STOCK = _bool("LIVE_STOCK", "true")

    # --- web --------------------------------------------------------------
    # The storefront origin(s) allowed to call this API.
    CORS_ORIGINS = _list("CORS_ORIGINS", "")
    ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")          # required for /admin/*
    RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "60"))

    # --- product links ----------------------------------------------------
    SITE_URL = os.getenv("SITE_URL", "").rstrip("/")

    # --- optional LLM (free-text understanding only) ----------------------
    # Any OpenAI-compatible endpoint works: Groq, Mistral, Gemini, Ollama,
    # OpenAI. Only the base URL, key and model name change — no code change.
    # Keeping this swappable matters: the engine must not depend on one vendor.
    ENABLE_INTERPRET = _bool("ENABLE_INTERPRET", "false")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL",
                             "https://api.groq.com/openai/v1")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "20"))

    # --- semantic search (optional) ---------------------------------------
    # "local" = sentence-transformers, offline and free, no key needed
    # "api"   = any OpenAI-compatible /embeddings endpoint
    # "off"   = disabled; the system falls back to keyword search everywhere
    EMBED_BACKEND = os.getenv("EMBED_BACKEND", "off").strip().lower()
    EMBED_MODEL = os.getenv("EMBED_MODEL", "")
    EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "")
    EMBED_API_KEY = os.getenv("EMBED_API_KEY", "")
    # Minimum cosine similarity for a semantic hit. Model-dependent: raise it
    # if results look loose, lower it if relevant products are being missed.
    EMBED_MIN_SCORE = float(os.getenv("EMBED_MIN_SCORE", "0.15"))

    # --- exclusions -------------------------------------------------------
    EXCLUDED_CATEGORY_SLUGS = _list(
        "EXCLUDED_CATEGORY_SLUGS",
        "accueil,promos,destockage,racine,uncategorized",
    )


settings = Settings()
