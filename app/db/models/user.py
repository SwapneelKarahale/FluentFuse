from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON, Enum as SQLEnum, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
import enum
from datetime import datetime
from typing import List, Dict, Optional

from app.db.base import Base


class UserRole(enum.Enum):
    """User role enumeration"""
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"


class OnboardingState(enum.Enum):
    """User onboarding state enumeration"""
    INCOMPLETE = "incomplete"
    LANGUAGE_SETUP = "language_setup"
    PROFICIENCY_TEST = "proficiency_test"
    INTERESTS = "interests"
    AVAILABILITY = "availability"
    COMPLETED = "completed"


class AgeGroup(enum.Enum):
    """Age group enumeration for matching and safety"""
    TEEN_13_17 = "teen_13_17"
    YOUNG_ADULT_18_25 = "young_adult_18_25"
    ADULT_26_35 = "adult_26_35"
    ADULT_36_45 = "adult_36_45"
    ADULT_46_55 = "adult_46_55"
    SENIOR_56_PLUS = "senior_56_plus"


class CEFRLevel(enum.Enum):
    """CEFR proficiency levels"""
    A1 = "A1"  # Beginner
    A2 = "A2"  # Elementary
    B1 = "B1"  # Intermediate
    B2 = "B2"  # Upper Intermediate
    C1 = "C1"  # Advanced
    C2 = "C2"  # Proficient
    NATIVE = "NATIVE"  # Native speaker


class User(Base):
    """User model for language learners"""
    __tablename__ = "users"
    
    # Primary identification
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    handle = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password = Column(String(128), nullable=False)
    
    # Personal information
    display_name = Column(String(100), nullable=True)
    bio = Column(Text, nullable=True)
    timezone = Column(String(50), nullable=False, default="UTC")
    age_group = Column(SQLEnum(AgeGroup), nullable=False)
    
    # Account status
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    is_banned = Column(Boolean, default=False, nullable=False)
    role = Column(SQLEnum(UserRole), default=UserRole.USER, nullable=False)
    
    # Onboarding
    onboard_state = Column(SQLEnum(OnboardingState), default=OnboardingState.INCOMPLETE, nullable=False)
    
    # Language information (stored as JSON arrays and objects)
    native_langs = Column(ARRAY(String(10)), nullable=False, default=[])  # ISO language codes
    target_langs = Column(ARRAY(String(10)), nullable=False, default=[])  # ISO language codes
    
    # Proficiency mapping: {"en": "NATIVE", "ja": "B1", "fr": "A2"}
    proficiency_map = Column(JSON, nullable=False, default={})
    
    # Interests and preferences
    interests = Column(ARRAY(String(50)), nullable=False, default=[])  # Topic tags
    
    # Learning goals and motivation
    goals = Column(JSON, nullable=True)  # {"primary": "conversation", "target_fluency": "B2", "timeline": "6_months"}
    
    # Availability windows (JSON array of time windows)
    # Format: [{"day": "monday", "start": "09:00", "end": "17:00", "timezone": "UTC"}]
    availability_windows = Column(JSON, nullable=False, default=[])
    
    # Profile customization
    avatar_url = Column(String(500), nullable=True)
    theme_preference = Column(String(20), default="light", nullable=False)
    language_interface = Column(String(10), default="en", nullable=False)  # UI language
    
    # Privacy and safety settings
    profile_visibility = Column(String(20), default="public", nullable=False)  # public, friends, private
    allow_minor_matching = Column(Boolean, default=False, nullable=False)  # For adults
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    
    # Statistics and metrics (denormalized for performance)
    total_sessions = Column(Integer, default=0, nullable=False)
    total_session_minutes = Column(Integer, default=0, nullable=False)
    current_streak_days = Column(Integer, default=0, nullable=False)
    longest_streak_days = Column(Integer, default=0, nullable=False)
    total_xp = Column(Integer, default=0, nullable=False)
    current_level = Column(Integer, default=1, nullable=False)
    
    # Relationships
    # devices = relationship("Device", back_populates="user", cascade="all, delete-orphan")
    # profile_prefs = relationship("ProfilePrefs", back_populates="user", uselist=False, cascade="all, delete-orphan")
    # match_candidates = relationship("MatchCandidate", back_populates="user", uselist=False, cascade="all, delete-orphan")
    # vocab_items = relationship("VocabItem", back_populates="owner", cascade="all, delete-orphan")
    # streaks = relationship("Streak", back_populates="user", uselist=False, cascade="all, delete-orphan")
    # notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    
    # Indexes for performance
    __table_args__ = (
        Index('ix_user_native_target_langs', 'native_langs', 'target_langs'),
        Index('ix_user_age_group_active', 'age_group', 'is_active'),
        Index('ix_user_onboard_state', 'onboard_state'),
        Index('ix_user_created_at', 'created_at'),
        Index('ix_user_last_login', 'last_login_at'),
    )
    
    def __repr__(self):
        return f"<User(id={self.id}, handle={self.handle}, email={self.email})>"
    
    @property
    def is_onboarded(self) -> bool:
        """Check if user has completed onboarding"""
        return self.onboard_state == OnboardingState.COMPLETED
    
    @property
    def can_match(self) -> bool:
        """Check if user can be matched with others"""
        return (
            self.is_active and 
            not self.is_banned and 
            self.is_onboarded and
            len(self.native_langs) > 0 and 
            len(self.target_langs) > 0
        )
    
    def get_proficiency(self, language: str) -> Optional[CEFRLevel]:
        """Get proficiency level for a specific language"""
        level_str = self.proficiency_map.get(language)
        if level_str:
            try:
                return CEFRLevel(level_str)
            except ValueError:
                return None
        return None
    
    def set_proficiency(self, language: str, level: CEFRLevel):
        """Set proficiency level for a specific language"""
        if self.proficiency_map is None:
            self.proficiency_map = {}
        self.proficiency_map[language] = level.value
    
    def is_native_speaker(self, language: str) -> bool:
        """Check if user is native speaker of given language"""
        return language in (self.native_langs or [])
    
    def is_learning(self, language: str) -> bool:
        """Check if user is learning given language"""
        return language in (self.target_langs or [])
    
    def has_common_interests(self, other_interests: List[str]) -> bool:
        """Check if user has any common interests with given list"""
        if not self.interests or not other_interests:
            return False
        return bool(set(self.interests) & set(other_interests))
    
    def get_xp_for_next_level(self) -> int:
        """Calculate XP needed for next level"""
        # Simple exponential formula: level^2 * 100
        next_level = self.current_level + 1
        return (next_level ** 2) * 100
    
    def add_xp(self, points: int) -> bool:
        """Add XP and check if level increased"""
        old_level = self.current_level
        self.total_xp += points
        
        # Calculate new level
        # Level = floor(sqrt(total_xp / 100))
        import math
        new_level = max(1, int(math.sqrt(self.total_xp / 100)))
        self.current_level = new_level
        
        return new_level > old_level
    
    def update_streak(self, days: int):
        """Update streak information"""
        self.current_streak_days = days
        if days > self.longest_streak_days:
            self.longest_streak_days = days
    
    def increment_session_stats(self, duration_minutes: int):
        """Increment session statistics"""
        self.total_sessions += 1
        self.total_session_minutes += duration_minutes
    
    def to_dict(self, include_sensitive: bool = False) -> Dict:
        """Convert user to dictionary"""
        data = {
            "id": str(self.id),
            "handle": self.handle,
            "display_name": self.display_name,
            "bio": self.bio,
            "timezone": self.timezone,
            "age_group": self.age_group.value if self.age_group else None,
            "native_langs": self.native_langs or [],
            "target_langs": self.target_langs or [],
            "proficiency_map": self.proficiency_map or {},
            "interests": self.interests or [],
            "goals": self.goals,
            "avatar_url": self.avatar_url,
            "theme_preference": self.theme_preference,
            "language_interface": self.language_interface,
            "profile_visibility": self.profile_visibility,
            "total_sessions": self.total_sessions,
            "total_session_minutes": self.total_session_minutes,
            "current_streak_days": self.current_streak_days,
            "longest_streak_days": self.longest_streak_days,
            "total_xp": self.total_xp,
            "current_level": self.current_level,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "is_onboarded": self.is_onboarded,
            "can_match": self.can_match,
        }
        
        if include_sensitive:
            data.update({
                "email": self.email,
                "is_active": self.is_active,
                "is_verified": self.is_verified,
                "is_banned": self.is_banned,
                "role": self.role.value if self.role else None,
                "onboard_state": self.onboard_state.value if self.onboard_state else None,
                "availability_windows": self.availability_windows or [],
                "allow_minor_matching": self.allow_minor_matching,
                "email_verified_at": self.email_verified_at.isoformat() if self.email_verified_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            })
        
        return data


class Device(Base):
    """User device for push notifications"""
    __tablename__ = "devices"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    
    # Device information
    push_token = Column(String(500), nullable=False, unique=True)
    platform = Column(String(20), nullable=False)  # ios, android, web
    device_name = Column(String(100), nullable=True)
    app_version = Column(String(20), nullable=True)
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('user_id', 'push_token', name='uq_user_device_token'),
        Index('ix_device_user_active', 'user_id', 'is_active'),
    )
    
    def __repr__(self):
        return f"<Device(id={self.id}, user_id={self.user_id}, platform={self.platform})>"


class ProfilePrefs(Base):
    """User profile preferences and safety settings"""
    __tablename__ = "profile_prefs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    
    # Content preferences
    avoid_topics = Column(ARRAY(String(50)), nullable=False, default=[])  # Topics to avoid
    preferred_session_length = Column(Integer, default=25, nullable=False)  # Minutes
    
    # Safety settings
    safety_level = Column(String(20), default="standard", nullable=False)  # strict, standard, relaxed
    auto_translate_enabled = Column(Boolean, default=True, nullable=False)
    profanity_filter_enabled = Column(Boolean, default=True, nullable=False)
    
    # Matching preferences
    same_age_group_only = Column(Boolean, default=False, nullable=False)
    same_timezone_preferred = Column(Boolean, default=False, nullable=False)
    min_partner_rating = Column(Integer, default=3, nullable=False)  # 1-5 scale
    
    # Notification preferences
    email_notifications = Column(Boolean, default=True, nullable=False)
    push_notifications = Column(Boolean, default=True, nullable=False)
    session_reminders = Column(Boolean, default=True, nullable=False)
    streak_reminders = Column(Boolean, default=True, nullable=False)
    
    # Privacy settings
    show_online_status = Column(Boolean, default=True, nullable=False)
    allow_session_recordings = Column(Boolean, default=False, nullable=False)
    data_sharing_consent = Column(Boolean, default=False, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    def __repr__(self):
        return f"<ProfilePrefs(id={self.id}, user_id={self.user_id})>"