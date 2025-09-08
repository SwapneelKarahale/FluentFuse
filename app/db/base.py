from sqlalchemy import create_engine, MetaData
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import NullPool
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from loguru import logger

from app.config import settings

# Create SQLAlchemy declarative base
Base = declarative_base()

# Create metadata with naming convention for constraints
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s", 
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s"
    }
)

# Assign metadata to Base
Base.metadata = metadata

# Create sync engine for migrations and admin tasks
sync_engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DATABASE_ECHO,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,  # Verify connections before use
    pool_recycle=3600,   # Recycle connections every hour
)

# Create async engine for main application
engine = create_async_engine(
    settings.database_url_async,
    echo=settings.DATABASE_ECHO,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=3600,
    # Use NullPool for WebSocket connections to prevent pool exhaustion
    poolclass=NullPool if settings.ENVIRONMENT == "development" else None,
)

# Create session factories
SessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False
)


# Dependency to get sync database session (for migrations, admin tasks)
def get_sync_db() -> Session:
    """Get synchronous database session"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database session error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


# Dependency to get async database session (main application)
async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """Get asynchronous database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"Async database session error: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()


# Context manager for manual async session handling
@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for async database sessions"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            logger.error(f"Async session context error: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()


# Context manager for manual sync session handling
@asynccontextmanager
async def get_sync_session() -> Session:
    """Context manager for sync database sessions"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        logger.error(f"Sync session context error: {e}")
        session.rollback()
        raise
    finally:
        session.close()


# Database initialization utilities
async def init_db() -> None:
    """Initialize database tables"""
    try:
        # Import all models to ensure they're registered
        from app.db.models import user, match, session, message, vocab  # noqa
        
        async with engine.begin() as conn:
            # Create all tables
            await conn.run_sync(Base.metadata.create_all)
            logger.info("✅ Database tables created successfully")
            
    except Exception as e:
        logger.error(f"❌ Failed to initialize database: {e}")
        raise


async def drop_db() -> None:
    """Drop all database tables (use with caution!)"""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            logger.warning("🗑️ All database tables dropped")
            
    except Exception as e:
        logger.error(f"❌ Failed to drop database: {e}")
        raise


def init_sync_db() -> None:
    """Initialize database tables synchronously (for scripts)"""
    try:
        # Import all models
        from app.db.models import user, match, session, message, vocab  # noqa
        
        Base.metadata.create_all(bind=sync_engine)
        logger.info("✅ Database tables created successfully (sync)")
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize database (sync): {e}")
        raise


# Health check utilities
async def check_db_health() -> bool:
    """Check database connection health"""
    try:
        async with AsyncSessionLocal() as session:
            # Simple query to test connection
            result = await session.execute("SELECT 1")
            return result.scalar() == 1
            
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False


def check_sync_db_health() -> bool:
    """Check sync database connection health"""
    try:
        with SessionLocal() as session:
            result = session.execute("SELECT 1")
            return result.scalar() == 1
            
    except Exception as e:
        logger.error(f"Sync database health check failed: {e}")
        return False


# Transaction utilities
class DatabaseTransaction:
    """Context manager for database transactions with rollback support"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.transaction = None
    
    async def __aenter__(self):
        self.transaction = await self.session.begin()
        return self.session
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            await self.transaction.rollback()
            logger.error(f"Transaction rolled back due to: {exc_val}")
        else:
            await self.transaction.commit()


# Database statistics and monitoring
async def get_db_stats() -> dict:
    """Get database connection pool statistics"""
    try:
        pool = engine.pool
        return {
            "pool_size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "invalid": pool.invalid(),
        }
    except Exception as e:
        logger.error(f"Failed to get database stats: {e}")
        return {"error": str(e)}


# Utility functions for common operations
async def execute_raw_query(query: str, params: dict = None) -> list:
    """Execute raw SQL query safely"""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(query, params or {})
            if query.strip().lower().startswith(('insert', 'update', 'delete')):
                await session.commit()
                return [{"affected_rows": result.rowcount}]
            else:
                return [dict(row) for row in result.fetchall()]
        except Exception as e:
            await session.rollback()
            logger.error(f"Raw query execution failed: {e}")
            raise


# Database connection event handlers
from sqlalchemy import event
from sqlalchemy.pool import Pool

@event.listens_for(Pool, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Set database-specific settings on connection"""
    if 'postgresql' in settings.DATABASE_URL:
        # Set PostgreSQL specific settings
        cursor = dbapi_connection.cursor()
        # Set timezone to UTC
        cursor.execute("SET timezone TO 'UTC'")
        # Set statement timeout (30 seconds)
        cursor.execute("SET statement_timeout TO '30s'")
        cursor.close()


@event.listens_for(Pool, "checkout")
def receive_checkout(dbapi_connection, connection_record, connection_proxy):
    """Log database connection checkout"""
    if settings.DATABASE_ECHO:
        logger.debug("Database connection checked out from pool")


@event.listens_for(Pool, "checkin")
def receive_checkin(dbapi_connection, connection_record):
    """Log database connection checkin"""
    if settings.DATABASE_ECHO:
        logger.debug("Database connection checked in to pool")


# Export commonly used items
__all__ = [
    "Base",
    "metadata", 
    "engine",
    "sync_engine",
    "AsyncSessionLocal",
    "SessionLocal",
    "get_async_db",
    "get_sync_db",
    "get_async_session",
    "get_sync_session",
    "init_db",
    "drop_db",
    "init_sync_db",
    "check_db_health",
    "check_sync_db_health",
    "DatabaseTransaction",
    "get_db_stats",
    "execute_raw_query"
]