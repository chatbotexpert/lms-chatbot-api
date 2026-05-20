import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

# Load environment variables
load_dotenv()

# Database URL configuration (PostgreSQL with asyncpg driver)
DATABASE_URL = os.getenv("DATABASE_URL")

# Create asynchronous engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
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
