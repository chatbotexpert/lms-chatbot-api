import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# Load environment variables
load_dotenv()

# Database URL configuration (PostgreSQL with asyncpg driver)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/lms_rag"

# Auto-correct postgresql:// to postgresql+asyncpg://
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Clean query parameters for asyncpg (e.g. sslmode, channel_binding)
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

    # Rebuild URL without the unsupported parameters
    new_query = urlencode(query_params)
    DATABASE_URL = urlunparse(parsed_url._replace(query=new_query))
    
    if use_ssl:
        connect_args["ssl"] = True
except Exception:
    pass

# Create asynchronous engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args=connect_args
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
