import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy.engine.url import URL

# Load .env file. override=True makes sure local .env settings take priority over stale system env vars.
load_dotenv(override=True)

# ── Build connection URL from individual parts ────────────────────────────────
# This avoids ALL URL-parsing issues caused by special characters (e.g. @)
# in the password. Each value is passed as a plain string, no encoding needed.

# If DATABASE_URL is set (legacy / Neon), fall back to parsing it.
# Otherwise, use individual DB_* variables (preferred for Docker deployments).
_raw_url = os.getenv("DATABASE_URL", "")

if _raw_url and "neon.tech" not in _raw_url:
    # It's a non-Neon URL — parse individual components safely using SQLAlchemy's URL builder
    # We still use individual env vars as the primary method for Docker
    pass

# Individual env vars take priority (cleanest for Docker)
DB_HOST     = os.getenv("DB_HOST")
DB_PORT     = os.getenv("DB_PORT")
DB_USER     = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME     = os.getenv("DB_NAME")

if DB_HOST and DB_USER and DB_PASSWORD and DB_NAME:
    # Use individual vars — no URL parsing, no encoding issues
    engine_url = URL.create(
        drivername="postgresql+asyncpg",
        username=DB_USER,
        password=DB_PASSWORD,   # SQLAlchemy handles special chars automatically
        host=DB_HOST,
        port=int(DB_PORT) if DB_PORT else 5432,
        database=DB_NAME,
    )
    connect_args = {}
    use_ssl = os.getenv("DB_SSL", "false").lower() in ("true", "1", "yes")
    if use_ssl:
        connect_args["ssl"] = True
else:
    # Fallback: parse DATABASE_URL string (legacy support / Neon)
    from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

    DATABASE_URL = _raw_url or "postgresql+asyncpg://postgres:postgres@localhost:5432/lms_rag"

    if DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

    connect_args = {}
    try:
        parsed_url = urlparse(DATABASE_URL)
        query_params = dict(parse_qsl(parsed_url.query))

        use_ssl = False
        if "sslmode" in query_params:
            if query_params["sslmode"] in ("require", "verify-full", "verify-ca"):
                use_ssl = True
            del query_params["sslmode"]

        if "channel_binding" in query_params:
            del query_params["channel_binding"]

        new_query = urlencode(query_params)
        DATABASE_URL = urlunparse(parsed_url._replace(query=new_query))

        if use_ssl:
            connect_args["ssl"] = True
    except Exception:
        pass

    engine_url = DATABASE_URL

from sqlalchemy.pool import NullPool

# ── Create async engine ───────────────────────────────────────────────────────
engine = create_async_engine(
    engine_url,
    echo=False,
    future=True,
    connect_args=connect_args,
    poolclass=NullPool,
)

# Async session maker
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Declarative base class
Base = declarative_base()

# Dependency to get db session in FastAPI endpoints
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
