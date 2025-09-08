from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import redis
import json
import time
from typing import Dict, Optional, Tuple
from loguru import logger

from app.config import settings


class TokenBucket:
    """Token bucket algorithm implementation for rate limiting"""
    
    def __init__(self, capacity: int, refill_rate: int, refill_period: int = 60):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate  # tokens per refill_period
        self.refill_period = refill_period  # seconds
        self.last_refill = time.time()
    
    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens from bucket"""
        now = time.time()
        
        # Refill tokens based on elapsed time
        elapsed = now - self.last_refill
        if elapsed >= self.refill_period:
            periods = int(elapsed // self.refill_period)
            self.tokens = min(self.capacity, self.tokens + (self.refill_rate * periods))
            self.last_refill = now
        
        # Try to consume tokens
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False
    
    def to_dict(self) -> dict:
        """Serialize bucket state"""
        return {
            "capacity": self.capacity,
            "tokens": self.tokens,
            "refill_rate": self.refill_rate,
            "refill_period": self.refill_period,
            "last_refill": self.last_refill
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TokenBucket":
        """Deserialize bucket state"""
        bucket = cls(data["capacity"], data["refill_rate"], data["refill_period"])
        bucket.tokens = data["tokens"]
        bucket.last_refill = data["last_refill"]
        return bucket


class RedisRateLimiter:
    """Redis-based distributed rate limiter"""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.default_limits = {
            # General API limits
            "default": {"capacity": 60, "refill_rate": 60, "period": 60},  # 60 req/min
            "auth": {"capacity": 10, "refill_rate": 10, "period": 60},     # 10 auth req/min
            "match": {"capacity": 20, "refill_rate": 20, "period": 60},    # 20 match req/min
            
            # WebSocket limits
            "ws_connect": {"capacity": 5, "refill_rate": 5, "period": 60}, # 5 connections/min
            "ws_message": {"capacity": 120, "refill_rate": 120, "period": 60}, # 2 msg/sec
            
            # User content limits
            "vocab_save": {"capacity": 30, "refill_rate": 30, "period": 60}, # 30 saves/min
            "feedback": {"capacity": 10, "refill_rate": 10, "period": 300},   # 10 feedback/5min
            "report": {"capacity": 5, "refill_rate": 5, "period": 3600},      # 5 reports/hour
            
            # Heavy operations
            "session_create": {"capacity": 10, "refill_rate": 10, "period": 300}, # 10 sessions/5min
            "translation": {"capacity": 100, "refill_rate": 100, "period": 3600}, # 100 translations/hour
        }
    
    def _get_bucket_key(self, identifier: str, limit_type: str) -> str:
        """Generate Redis key for rate limit bucket"""
        return f"rate_limit:{limit_type}:{identifier}"
    
    def _get_bucket(self, identifier: str, limit_type: str) -> TokenBucket:
        """Get or create token bucket from Redis"""
        key = self._get_bucket_key(identifier, limit_type)
        
        try:
            bucket_data = self.redis.get(key)
            if bucket_data:
                data = json.loads(bucket_data)
                return TokenBucket.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Invalid bucket data for {key}: {e}")
        
        # Create new bucket with default limits
        limits = self.default_limits.get(limit_type, self.default_limits["default"])
        return TokenBucket(
            capacity=limits["capacity"],
            refill_rate=limits["refill_rate"],
            refill_period=limits["period"]
        )
    
    def _save_bucket(self, identifier: str, limit_type: str, bucket: TokenBucket):
        """Save token bucket to Redis"""
        key = self._get_bucket_key(identifier, limit_type)
        bucket_data = json.dumps(bucket.to_dict())
        
        # Set expiry to prevent memory leaks
        expiry = bucket.refill_period * 2
        self.redis.setex(key, expiry, bucket_data)
    
    def is_allowed(self, identifier: str, limit_type: str = "default", tokens: int = 1) -> Tuple[bool, Dict]:
        """Check if request is allowed and return status"""
        bucket = self._get_bucket(identifier, limit_type)
        allowed = bucket.consume(tokens)
        
        # Save bucket state
        self._save_bucket(identifier, limit_type, bucket)
        
        # Return status info
        status_info = {
            "allowed": allowed,
            "limit_type": limit_type,
            "tokens_remaining": bucket.tokens,
            "capacity": bucket.capacity,
            "reset_time": bucket.last_refill + bucket.refill_period
        }
        
        return allowed, status_info
    
    def get_status(self, identifier: str, limit_type: str = "default") -> Dict:
        """Get current rate limit status without consuming tokens"""
        bucket = self._get_bucket(identifier, limit_type)
        
        return {
            "limit_type": limit_type,
            "tokens_remaining": bucket.tokens,
            "capacity": bucket.capacity,
            "reset_time": bucket.last_refill + bucket.refill_period
        }


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for rate limiting"""
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.redis_client = redis.from_url(settings.REDIS_URL)
        self.rate_limiter = RedisRateLimiter(self.redis_client)
        
        # Route-specific rate limit mapping
        self.route_limits = {
            "/api/v1/auth/login": "auth",
            "/api/v1/auth/register": "auth",
            "/api/v1/auth/refresh": "auth",
            "/api/v1/match/queue": "match",
            "/api/v1/match/accept": "match",
            "/api/v1/sessions": "session_create",
            "/api/v1/vocab": "vocab_save",
            "/api/v1/feedback": "feedback",
            "/api/v1/report": "report",
            "/api/v1/translate": "translation",
        }
        
        # Exempt routes from rate limiting
        self.exempt_routes = {
            "/health",
            "/",
            "/docs",
            "/redoc",
            "/openapi.json"
        }
    
    def _get_client_identifier(self, request: Request) -> str:
        """Get client identifier for rate limiting"""
        # Try to get user ID from JWT token first
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            try:
                # This would normally decode JWT to get user_id
                # For now, use the token itself as identifier
                return f"user:{auth_header[7:][:20]}"  # First 20 chars of token
            except Exception:
                pass
        
        # Fallback to IP address
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return f"ip:{forwarded_for.split(',')[0].strip()}"
        
        client_host = getattr(request.client, 'host', 'unknown')
        return f"ip:{client_host}"
    
    def _get_limit_type(self, request: Request) -> str:
        """Determine rate limit type based on route"""
        path = request.url.path
        
        # Check exact matches first
        if path in self.route_limits:
            return self.route_limits[path]
        
        # Check prefix matches
        for route_prefix, limit_type in self.route_limits.items():
            if path.startswith(route_prefix):
                return limit_type
        
        return "default"
    
    async def dispatch(self, request: Request, call_next):
        """Process rate limiting for incoming requests"""
        
        # Skip rate limiting for exempt routes
        if request.url.path in self.exempt_routes:
            return await call_next(request)
        
        # Skip rate limiting in development if configured
        if settings.is_development and not settings.DEBUG:
            return await call_next(request)
        
        try:
            # Get client identifier and limit type
            identifier = self._get_client_identifier(request)
            limit_type = self._get_limit_type(request)
            
            # Check rate limit
            allowed, status_info = self.rate_limiter.is_allowed(identifier, limit_type)
            
            if not allowed:
                logger.warning(f"Rate limit exceeded for {identifier} on {request.url.path}")
                
                # Return rate limit error
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": "Rate limit exceeded",
                        "message": f"Too many requests for {limit_type}",
                        "retry_after": int(status_info["reset_time"] - time.time()),
                        "limit_info": {
                            "type": limit_type,
                            "capacity": status_info["capacity"],
                            "reset_time": status_info["reset_time"]
                        }
                    },
                    headers={
                        "X-RateLimit-Limit": str(status_info["capacity"]),
                        "X-RateLimit-Remaining": str(status_info["tokens_remaining"]),
                        "X-RateLimit-Reset": str(int(status_info["reset_time"])),
                        "Retry-After": str(int(status_info["reset_time"] - time.time()))
                    }
                )
            
            # Process request
            response = await call_next(request)
            
            # Add rate limit headers to successful responses
            response.headers["X-RateLimit-Limit"] = str(status_info["capacity"])
            response.headers["X-RateLimit-Remaining"] = str(status_info["tokens_remaining"])
            response.headers["X-RateLimit-Reset"] = str(int(status_info["reset_time"]))
            
            return response
            
        except Exception as e:
            logger.error(f"Rate limiter error: {e}")
            # If rate limiter fails, allow the request to proceed
            return await call_next(request)


# Utility functions for manual rate limiting in routes
async def check_rate_limit(request: Request, limit_type: str = "default", tokens: int = 1) -> bool:
    """Manual rate limit check for specific endpoints"""
    try:
        redis_client = redis.from_url(settings.REDIS_URL)
        rate_limiter = RedisRateLimiter(redis_client)
        
        # Get client identifier
        middleware = RateLimiterMiddleware(None)
        identifier = middleware._get_client_identifier(request)
        
        allowed, _ = rate_limiter.is_allowed(identifier, limit_type, tokens)
        return allowed
        
    except Exception as e:
        logger.error(f"Manual rate limit check error: {e}")
        return True  # Allow on error


async def get_rate_limit_status(request: Request, limit_type: str = "default") -> Dict:
    """Get current rate limit status for debugging"""
    try:
        redis_client = redis.from_url(settings.REDIS_URL)
        rate_limiter = RedisRateLimiter(redis_client)
        
        # Get client identifier
        middleware = RateLimiterMiddleware(None)
        identifier = middleware._get_client_identifier(request)
        
        return rate_limiter.get_status(identifier, limit_type)
        
    except Exception as e:
        logger.error(f"Rate limit status error: {e}")
        return {"error": str(e)}