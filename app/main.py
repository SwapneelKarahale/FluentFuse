from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from contextlib import asynccontextmanager
import redis
from loguru import logger

from app.config import settings
from app.db.base import engine, Base
from app.core.rate_limiter import RateLimiterMiddleware
# from app.api.v1 import auth, users, match, sessions, messages, vocab, streaks, challenges, feedback
# from app.api.v1.websocket import chat_ws


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown events"""
    # Startup
    logger.info("🚀 Starting Language Exchange Platform...")
    
    # Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Test Redis connection
    try:
        redis_client = redis.from_url(settings.REDIS_URL)
        redis_client.ping()
        logger.info("✅ Redis connection established")
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")
        raise
    
    logger.info("✅ Application startup complete")
    
    yield
    
    # Shutdown
    logger.info("🔄 Shutting down Language Exchange Platform...")
    # Clean up resources if needed
    logger.info("✅ Application shutdown complete")


# Create FastAPI application
app = FastAPI(
    title="Language Exchange Platform API",
    description="Real-time language learning and practice platform",
    version="1.0.0",
    docs_url="/docs" if settings.ENVIRONMENT == "development" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT == "development" else None,
    lifespan=lifespan
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Add trusted host middleware for production
if settings.ENVIRONMENT == "production":
    app.add_middleware(
        TrustedHostMiddleware, 
        allowed_hosts=settings.ALLOWED_HOSTS
    )

# Add rate limiting middleware
app.add_middleware(RateLimiterMiddleware)

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "environment": settings.ENVIRONMENT
    }

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Language Exchange Platform API",
        "version": "1.0.0",
        "docs": "/docs" if settings.ENVIRONMENT == "development" else "disabled",
        "health": "/health"
    }

# Include API routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(match.router, prefix="/api/v1/match", tags=["Matching"])
app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["Sessions"])
app.include_router(messages.router, prefix="/api/v1/messages", tags=["Messages"])
app.include_router(vocab.router, prefix="/api/v1/vocab", tags=["Vocabulary"])
app.include_router(streaks.router, prefix="/api/v1/streaks", tags=["Streaks"])
app.include_router(challenges.router, prefix="/api/v1/challenges", tags=["Challenges"])
app.include_router(feedback.router, prefix="/api/v1/feedback", tags=["Feedback"])

# Include WebSocket router
app.include_router(chat_ws.router, prefix="/api/v1/ws", tags=["WebSocket"])

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}")
    return {
        "error": "Internal server error",
        "message": "An unexpected error occurred"
    }

if __name__ == "__main__":
    import uvicorn
    
    logger.info("🔧 Starting development server...")
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.ENVIRONMENT == "development",
        log_level="info"
    )