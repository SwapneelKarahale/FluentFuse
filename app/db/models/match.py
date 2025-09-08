from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, JSON, Enum as SQLEnum, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
import enum
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

from app.db.base import Base


class MatchCandidateStatus(enum.Enum):
    """Match candidate status enumeration"""
    IDLE = "idle"                    # Available for matching
    QUEUED = "queued"               # In matching queue
    PROPOSED = "proposed"           # Has pending match proposal
    MATCHED = "matched"             # Currently in active session
    COOLDOWN = "cooldown"          # Temporary cooldown after rejection


class MatchState(enum.Enum):
    """Match state enumeration"""
    PROPOSED = "proposed"           # Match proposed to both users
    ACCEPTED = "accepted"           # Both users accepted, session can be created
    REJECTED = "rejected"           # One or both users rejected
    EXPIRED = "expired"            # Proposal timed out
    SESSION_CREATED = "session_created"  # Session successfully created


class MatchCandidate(Base):
    """User's matching status and preferences"""
    __tablename__ = "match_candidates"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), 
                     nullable=False, unique=True, index=True)
    
    # Current matching status
    status = Column(SQLEnum(MatchCandidateStatus), default=MatchCandidateStatus.IDLE, nullable=False)
    
    # Queue and matching metadata
    queued_at = Column(DateTime(timezone=True), nullable=True)
    last_match_at = Column(DateTime(timezone=True), nullable=True)
    queue_priority = Column(Float, default=0.0, nullable=False)  # For priority matching (Pro users)
    
    # Quality metrics for matching algorithm
    average_rating = Column(Float, default=5.0, nullable=False)  # 1-5 scale
    total_ratings = Column(Integer, default=0, nullable=False)
    strike_count = Column(Integer, default=0, nullable=False)  # For repeated bad behavior
    successful_matches = Column(Integer, default=0, nullable=False)
    
    # Blocklist and restrictions
    blocked_user_ids = Column(ARRAY(UUID(as_uuid=True)), nullable=False, default=[])
    
    # Cooldown management
    cooldown_until = Column(DateTime(timezone=True), nullable=True)
    cooldown_reason = Column(String(100), nullable=True)
    rejection_count_today = Column(Integer, default=0, nullable=False)
    last_rejection_reset = Column(DateTime(timezone=True), nullable=True)
    
    # Matching preferences (can override user defaults)
    preferred_session_length = Column(Integer, nullable=True)  # Minutes, null = use user default
    max_level_difference = Column(Integer, default=2, nullable=False)  # CEFR level difference
    same_timezone_only = Column(Boolean, default=False, nullable=False)
    
    # Current active match
    current_match_id = Column(UUID(as_uuid=True), ForeignKey("matches.id"), nullable=True, index=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    # user = relationship("User", back_populates="match_candidate")
    # current_match = relationship("Match", foreign_keys=[current_match_id])
    
    # Indexes
    __table_args__ = (
        Index('ix_match_candidate_status_queued', 'status', 'queued_at'),
        Index('ix_match_candidate_priority', 'queue_priority', 'queued_at'),
        Index('ix_match_candidate_cooldown', 'cooldown_until'),
        Index('ix_match_candidate_last_match', 'last_match_at'),
    )
    
    def __repr__(self):
        return f"<MatchCandidate(id={self.id}, user_id={self.user_id}, status={self.status})>"
    
    @property
    def is_available(self) -> bool:
        """Check if candidate is available for matching"""
        now = datetime.utcnow()
        return (
            self.status == MatchCandidateStatus.IDLE and
            (self.cooldown_until is None or self.cooldown_until <= now) and
            self.strike_count < 3  # Max strikes before temporary ban
        )
    
    @property
    def is_in_cooldown(self) -> bool:
        """Check if candidate is in cooldown"""
        if self.cooldown_until is None:
            return False
        return datetime.utcnow() < self.cooldown_until
    
    def add_to_queue(self, priority: float = 0.0):
        """Add candidate to matching queue"""
        self.status = MatchCandidateStatus.QUEUED
        self.queued_at = datetime.utcnow()
        self.queue_priority = priority
    
    def remove_from_queue(self):
        """Remove candidate from matching queue"""
        self.status = MatchCandidateStatus.IDLE
        self.queued_at = None
        self.queue_priority = 0.0
    
    def add_cooldown(self, duration_minutes: int, reason: str = "rejection"):
        """Add cooldown period"""
        self.status = MatchCandidateStatus.COOLDOWN
        self.cooldown_until = datetime.utcnow() + timedelta(minutes=duration_minutes)
        self.cooldown_reason = reason
    
    def add_rating(self, rating: float):
        """Add new rating and update average"""
        total_score = self.average_rating * self.total_ratings
        self.total_ratings += 1
        self.average_rating = (total_score + rating) / self.total_ratings
    
    def add_strike(self):
        """Add behavioral strike"""
        self.strike_count += 1
        if self.strike_count >= 3:
            self.add_cooldown(60 * 24, "excessive_strikes")  # 24 hour cooldown
    
    def reset_daily_rejections(self):
        """Reset daily rejection count"""
        today = datetime.utcnow().date()
        if self.last_rejection_reset is None or self.last_rejection_reset.date() < today:
            self.rejection_count_today = 0
            self.last_rejection_reset = datetime.utcnow()
    
    def can_reject_more_today(self, max_rejections: int = 10) -> bool:
        """Check if user can reject more matches today"""
        self.reset_daily_rejections()
        return self.rejection_count_today < max_rejections
    
    def is_blocked_user(self, user_id: uuid.UUID) -> bool:
        """Check if user is in blocklist"""
        return user_id in (self.blocked_user_ids or [])
    
    def block_user(self, user_id: uuid.UUID):
        """Add user to blocklist"""
        if self.blocked_user_ids is None:
            self.blocked_user_ids = []
        if user_id not in self.blocked_user_ids:
            self.blocked_user_ids.append(user_id)
    
    def unblock_user(self, user_id: uuid.UUID):
        """Remove user from blocklist"""
        if self.blocked_user_ids and user_id in self.blocked_user_ids:
            self.blocked_user_ids.remove(user_id)


class Match(Base):
    """Match between two users"""
    __tablename__ = "matches"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # Matched users
    user1_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), 
                      nullable=False, index=True)
    user2_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), 
                      nullable=False, index=True)
    
    # Language configuration for this match
    languages = Column(JSON, nullable=False)  # {"primary": "ja", "secondary": "en"}
    
    # Match quality and metadata
    match_score = Column(Float, nullable=False)  # Matching algorithm score
    matching_factors = Column(JSON, nullable=False)  # What made this a good match
    
    # Match state and lifecycle
    state = Column(SQLEnum(MatchState), default=MatchState.PROPOSED, nullable=False)
    proposed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)  # Proposal expiry
    
    # User responses
    user1_response = Column(String(20), nullable=True)  # "accepted", "rejected", null
    user2_response = Column(String(20), nullable=True)  # "accepted", "rejected", null
    user1_responded_at = Column(DateTime(timezone=True), nullable=True)
    user2_responded_at = Column(DateTime(timezone=True), nullable=True)
    
    # Session information (once accepted)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True, index=True)
    
    # Rejection/failure metadata
    rejection_reason = Column(String(100), nullable=True)
    failure_reason = Column(String(100), nullable=True)  # Technical failures
    
    # Timestamps
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    # user1 = relationship("User", foreign_keys=[user1_id])
    # user2 = relationship("User", foreign_keys=[user2_id])
    # session = relationship("Session", back_populates="match")
    
    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint('user1_id', 'user2_id', name='uq_match_users'),
        Index('ix_match_state_expires', 'state', 'expires_at'),
        Index('ix_match_users_state', 'user1_id', 'user2_id', 'state'),
        Index('ix_match_proposed_at', 'proposed_at'),
    )
    
    def __repr__(self):
        return f"<Match(id={self.id}, user1={self.user1_id}, user2={self.user2_id}, state={self.state})>"
    
    @property
    def is_expired(self) -> bool:
        """Check if match proposal has expired"""
        return datetime.utcnow() > self.expires_at
    
    @property
    def is_pending(self) -> bool:
        """Check if match is waiting for user responses"""
        return self.state == MatchState.PROPOSED and not self.is_expired
    
    @property
    def is_fully_responded(self) -> bool:
        """Check if both users have responded"""
        return self.user1_response is not None and self.user2_response is not None
    
    @property
    def is_accepted_by_both(self) -> bool:
        """Check if both users accepted the match"""
        return self.user1_response == "accepted" and self.user2_response == "accepted"
    
    def get_partner_id(self, user_id: uuid.UUID) -> uuid.UUID:
        """Get partner's user ID"""
        if user_id == self.user1_id:
            return self.user2_id
        elif user_id == self.user2_id:
            return self.user1_id
        else:
            raise ValueError("User ID not found in this match")
    
    def get_user_response(self, user_id: uuid.UUID) -> Optional[str]:
        """Get user's response to match proposal"""
        if user_id == self.user1_id:
            return self.user1_response
        elif user_id == self.user2_id:
            return self.user2_response
        return None
    
    def set_user_response(self, user_id: uuid.UUID, response: str):
        """Set user's response to match proposal"""
        now = datetime.utcnow()
        
        if user_id == self.user1_id:
            self.user1_response = response
            self.user1_responded_at = now
        elif user_id == self.user2_id:
            self.user2_response = response
            self.user2_responded_at = now
        else:
            raise ValueError("User ID not found in this match")
        
        # Update match state if both responded
        self._update_state_after_response()
    
    def _update_state_after_response(self):
        """Update match state based on user responses"""
        if not self.is_fully_responded:
            return
        
        if self.is_accepted_by_both:
            self.state = MatchState.ACCEPTED
            self.accepted_at = datetime.utcnow()
        else:
            self.state = MatchState.REJECTED
            self.completed_at = datetime.utcnow()
            
            # Set rejection reason
            if self.user1_response == "rejected" and self.user2_response == "rejected":
                self.rejection_reason = "both_rejected"
            elif self.user1_response == "rejected":
                self.rejection_reason = "user1_rejected"
            else:
                self.rejection_reason = "user2_rejected"
    
    def expire_match(self):
        """Mark match as expired"""
        self.state = MatchState.EXPIRED
        self.completed_at = datetime.utcnow()
        
        # Set responses for users who didn't respond
        if self.user1_response is None:
            self.user1_response = "timeout"
        if self.user2_response is None:
            self.user2_response = "timeout"
    
    def create_session(self, session_id: uuid.UUID):
        """Associate match with created session"""
        self.session_id = session_id
        self.state = MatchState.SESSION_CREATED
    
    def calculate_match_quality_score(self, factors: Dict) -> float:
        """Calculate overall match quality from individual factors"""
        # Weights for different matching factors
        weights = {
            'level_affinity': 0.25,
            'native_target_match': 0.30,
            'interest_overlap': 0.20,
            'timezone_overlap': 0.15,
            'quality_score': 0.10,
        }
        
        score = 0.0
        for factor, weight in weights.items():
            if factor in factors:
                score += factors[factor] * weight
        
        return min(1.0, max(0.0, score))  # Clamp between 0 and 1
    
    def to_dict(self, current_user_id: Optional[uuid.UUID] = None) -> Dict:
        """Convert match to dictionary"""
        data = {
            "id": str(self.id),
            "state": self.state.value,
            "languages": self.languages,
            "match_score": self.match_score,
            "matching_factors": self.matching_factors,
            "proposed_at": self.proposed_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "is_expired": self.is_expired,
            "is_pending": self.is_pending,
        }
        
        if current_user_id:
            # Add user-specific information
            partner_id = self.get_partner_id(current_user_id)
            user_response = self.get_user_response(current_user_id)
            
            data.update({
                "partner_id": str(partner_id),
                "your_response": user_response,
                "is_fully_responded": self.is_fully_responded,
            })
        else:
            # Include all user information
            data.update({
                "user1_id": str(self.user1_id),
                "user2_id": str(self.user2_id),
                "user1_response": self.user1_response,
                "user2_response": self.user2_response,
                "user1_responded_at": self.user1_responded_at.isoformat() if self.user1_responded_at else None,
                "user2_responded_at": self.user2_responded_at.isoformat() if self.user2_responded_at else None,
            })
        
        if self.accepted_at:
            data["accepted_at"] = self.accepted_at.isoformat()
        if self.completed_at:
            data["completed_at"] = self.completed_at.isoformat()
        if self.session_id:
            data["session_id"] = str(self.session_id)
        if self.rejection_reason:
            data["rejection_reason"] = self.rejection_reason
        
        return data


class MatchHistory(Base):
    """Historical record of matches for analytics"""
    __tablename__ = "match_history"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    
    # Users involved
    user1_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user2_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    
    # Match outcome
    final_state = Column(SQLEnum(MatchState), nullable=False)
    match_score = Column(Float, nullable=False)
    response_time_seconds = Column(Integer, nullable=True)  # How long to respond
    
    # Session outcome (if session was created)
    session_completed = Column(Boolean, default=False, nullable=False)
    session_duration_minutes = Column(Integer, nullable=True)
    session_quality_rating = Column(Float, nullable=True)  # Average of both user ratings
    
    # Analytics metadata
    matching_factors = Column(JSON, nullable=False)
    user_feedback = Column(JSON, nullable=True)  # Post-match feedback
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Indexes
    __table_args__ = (
        Index('ix_match_history_users', 'user1_id', 'user2_id'),
        Index('ix_match_history_date', 'created_at'),
        Index('ix_match_history_outcome', 'final_state', 'session_completed'),
    )
    
    def __repr__(self):
        return f"<MatchHistory(id={self.id}, match_id={self.match_id}, state={self.final_state})>"
    