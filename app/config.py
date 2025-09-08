from pydantic_settings import BaseSettings
from pydantic import Field, validator
from typing import List, Optional
import secrets


class Settings(BaseSettings):
    """Application settings with environment variable support"""
    
    # Application settings
    APP_NAME: str = "Language Exchange Platform"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = Field(default="development", description="Environment: development, staging, production")
    DEBUG: bool = Field(default=False, description="Debug mode")
    
    # Server settings
    HOST: str = Field(default="0.0.0.0", description="Server host")
    PORT: int = Field(default=8000, description="Server port")
    
    # Security settings
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32), description="Secret key for JWT")
    ALGORITHM: str = Field(default="HS256", description="JWT algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, description="Access token expiration in minutes")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=30, description="Refresh token expiration in days")
    
    # CORS settings
    CORS_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed CORS origins"
    )
    ALLOWED_HOSTS: List[str] = Field(
        default=["localhost", "127.0.0.1"],
        description="Allowed hosts for production"
    )
    
    # Database settings
    DATABASE_URL: str = Field(
        default="postgresql://postgres:password@localhost:5432/language_exchange",
        description="PostgreSQL database URL"
    )
    DATABASE_ECHO: bool = Field(default=False, description="Echo SQL queries")
    DATABASE_POOL_SIZE: int = Field(default=10, description="Database connection pool size")
    DATABASE_MAX_OVERFLOW: int = Field(default=20, description="Database max overflow connections")
    
    # Redis settings
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL"
    )
    REDIS_EXPIRE_TIME: int = Field(default=3600, description="Default Redis expiration time in seconds")
    
    # Celery settings
    CELERY_BROKER_URL: str = Field(
        default="redis://localhost:6379/1",
        description="Celery broker URL"
    )
    CELERY_RESULT_BACKEND: str = Field(
        default="redis://localhost:6379/2",
        description="Celery result backend URL"
    )
    
    # Rate limiting settings
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(default=60, description="Rate limit per minute")
    RATE_LIMIT_BURST: int = Field(default=10, description="Rate limit burst capacity")
    
    # WebSocket settings
    WS_HEARTBEAT_INTERVAL: int = Field(default=30, description="WebSocket heartbeat interval in seconds")
    WS_MESSAGE_MAX_SIZE: int = Field(default=1024 * 10, description="Max WebSocket message size in bytes")
    WS_CONNECTION_TIMEOUT: int = Field(default=60, description="WebSocket connection timeout in seconds")
    
    # Matching engine settings
    MATCH_QUEUE_TTL: int = Field(default=300, description="Match queue TTL in seconds")
    MATCH_PROPOSAL_TTL: int = Field(default=90, description="Match proposal TTL in seconds")
    MATCH_COOLDOWN_MINUTES: int = Field(default=5, description="Match cooldown after rejection in minutes")
    MAX_QUEUE_SIZE: int = Field(default=1000, description="Maximum users in match queue")
    
    # Session settings
    SESSION_MAX_DURATION_HOURS: int = Field(default=2, description="Maximum session duration in hours")
    SESSION_TURN_SWITCH_MINUTES: int = Field(default=10, description="Minutes before suggesting language turn switch")
    SESSION_IDLE_TIMEOUT_MINUTES: int = Field(default=15, description="Session idle timeout in minutes")
    
    # Vocabulary & SRS settings
    SRS_DAILY_REVIEW_LIMIT: int = Field(default=50, description="Daily SRS review limit")
    SRS_INITIAL_INTERVAL_DAYS: int = Field(default=1, description="SRS initial interval in days")
    VOCAB_TRANSLATION_CACHE_HOURS: int = Field(default=24, description="Vocabulary translation cache in hours")
    
    # Streak settings
    STREAK_FREEZE_TOKENS_MAX: int = Field(default=3, description="Maximum streak freeze tokens")
    STREAK_GRACE_PERIOD_HOURS: int = Field(default=24, description="Streak grace period in hours")
    STREAK_TIMEZONE_UPDATE_INTERVAL_HOURS: int = Field(default=6, description="Timezone update check interval")
    
    # Challenge settings
    DAILY_CHALLENGE_COUNT: int = Field(default=10, description="Number of daily challenge items")
    CHALLENGE_WEAK_VOCAB_RATIO: float = Field(default=0.6, description="Ratio of weak vocab in challenges")
    CHALLENGE_XP_CORRECT_FIRST: int = Field(default=10, description="XP for correct first try")
    CHALLENGE_XP_CORRECT_SECOND: int = Field(default=5, description="XP for correct second try")
    
    # Email settings (optional)
    SMTP_SERVER: Optional[str] = Field(default=None, description="SMTP server for email")
    SMTP_PORT: int = Field(default=587, description="SMTP port")
    SMTP_USERNAME: Optional[str] = Field(default=None, description="SMTP username")
    SMTP_PASSWORD: Optional[str] = Field(default=None, description="SMTP password")
    SMTP_TLS: bool = Field(default=True, description="Use TLS for SMTP")
    EMAIL_FROM: Optional[str] = Field(default=None, description="From email address")
    
    # Safety & Moderation settings
    TOXICITY_THRESHOLD: float = Field(default=0.7, description="Toxicity detection threshold")
    PII_DETECTION_ENABLED: bool = Field(default=True, description="Enable PII detection")
    AUTO_MODERATION_ENABLED: bool = Field(default=True, description="Enable auto moderation")
    REPORT_THRESHOLD_FOR_REVIEW: int = Field(default=3, description="Reports needed for manual review")
    
    # File upload settings
    MAX_FILE_SIZE_MB: int = Field(default=10, description="Maximum file upload size in MB")
    ALLOWED_FILE_TYPES: List[str] = Field(
        default=["image/jpeg", "image/png", "image/webp", "audio/mpeg", "audio/wav"],
        description="Allowed file types for upload"
    )
    
    # Logging settings
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    LOG_FORMAT: str = Field(
        default="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        description="Log format"
    )
    
    @validator("ENVIRONMENT")
    def validate_environment(cls, v):
        if v not in ["development", "staging", "production"]:
            raise ValueError("ENVIRONMENT must be one of: development, staging, production")
        return v
    
    @validator("CORS_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v):
        if isinstance(v, str):
            return [i.strip() for i in v.split(",")]
        return v
    
    @validator("ALLOWED_HOSTS", pre=True)
    def assemble_allowed_hosts(cls, v):
        if isinstance(v, str):
            return [i.strip() for i in v.split(",")]
        return v
    
    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"
    
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"
    
    @property
    def database_url_async(self) -> str:
        """Convert sync database URL to async for SQLAlchemy"""
        if self.DATABASE_URL.startswith("postgresql://"):
            return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
        return self.DATABASE_URL
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Create settings instance
settings = Settings()

# Logging configuration
import sys
from loguru import logger

# Remove default logger
logger.remove()

# Add custom logger with format from settings
logger.add(
    sys.stdout,
    level=settings.LOG_LEVEL,
    format=settings.LOG_FORMAT,
    colorize=True,
    backtrace=True,
    diagnose=True
)

# Add file logger for production
if settings.is_production:
    logger.add(
        "logs/app.log",
        rotation="500 MB",
        retention="10 days",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
        compression="zip"
    )