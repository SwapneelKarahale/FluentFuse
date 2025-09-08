from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, JSON, Enum as SQLEnum, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
import enum
from datetime import datetime, timedelta
from typing import Dict, Optional, List

from app.db.base import Base


class SessionState(enum.Enum):
    """Session state enumeration"""
    ACTIVE = "active"               # Session is ongoing
    PAUSED = "paused"              # Temporarily paused (disconnection)
    ENDED = "ended"                # Normally completed
    DROPPED = "dropped"            # Abnormally terminated
    EXPIRED = "expired"            # Exceeded maximum duration


class TurnLanguage(enum.Enum):
    """Current turn language enumeration"""
    USER1_NATIVE = "user1_native"     # Speaking user1's native language
    USER2_NATIVE = "user2_native"     # Speaking user2's native language
    MIXED = "mixed"                   # Free conversation


class SessionEndReason(enum.Enum):
    """Session end reason enumeration"""
    COMPLETED = "completed"           # Normal completion
    USER_LEFT = "user_left"          # User voluntarily left
    INACTIVITY = "inactivity"        # Idle timeout
    TECHNICAL_ERROR = "technical_error"  # System issue
    MODERATION = "moderation"        # Ended by moderator
    MAXIMUM_DURATION = "maximum_duration"  # Hit time limit


class Session(Base):
    """Chat session between matched users"""
    __tablename__ = "sessions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # Link to match that created this session
    match_id = Column(UUID(as_uuid=True), ForeignKey("matches.id", ondelete="CASCADE"), 
                      nullable=False, unique=True, index=True)
    
    # Session participants
    user1_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), 
                      nullable=False, index=True)
    user2_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), 
                      nullable=False, index=True)
    
    # WebSocket room identifier
    room_id = Column(String(100), nullable=False, unique=True, index=True)
    
    # Session configuration
    languages = Column(JSON, nullable=False)  # {"primary": "ja", "secondary": "en", "user1_native": "en", "user2_native": "ja"}
    planned_duration_minutes = Column(Integer, default=25, nullable=False)
    
    # Current session state
    state = Column(SQLEnum(SessionState), default=SessionState.ACTIVE, nullable=False, index=True)
    current_turn_language = Column(SQLEnum(TurnLanguage), default=TurnLanguage.USER1_NATIVE, nullable=False)
    
    # Language turn management
    turn_switched_at = Column(DateTime(timezone=True), nullable=True)
    turn_switch_count = Column(Integer, default=0, nullable=False)
    auto_turn_switch_enabled = Column(Boolean, default=True, nullable=False)
    
    # Guided conversation
    prompt_pack_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    current_prompt_index = Column(Integer, default=0, nullable=False)
    prompts_used = Column(JSON, nullable=False, default=[])  # List of used prompt IDs
    
    # Session timeline
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    last_activity_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    paused_at = Column(DateTime(timezone=True), nullable=True)
    
    # Session metrics and statistics
    total_messages = Column(Integer, default=0, nullable=False)
    user1_message_count = Column(Integer, default=0, nullable=False)
    user2_message_count = Column(Integer, default=0, nullable=False)
    
    # Duration tracking (in seconds)
    active_duration_seconds = Column(Integer, default=0, nullable=False)
    paused_duration_seconds = Column(Integer, default=0, nullable=False)
    
    # User engagement metrics
    user1_last_seen = Column(DateTime(timezone=True), nullable=True)
    user2_last_seen = Column(DateTime(timezone=True), nullable=True)
    user1_typing = Column(Boolean, default=False, nullable=False)
    user2_typing = Column(Boolean, default=False, nullable=False)
    
    # Session quality and moderation
    toxicity_warnings = Column(Integer, default=0, nullable=False)
    moderation_flags = Column(JSON, nullable=False, default=[])  # List of moderation events
    
    # Session completion
    end_reason = Column(SQLEnum(SessionEndReason), nullable=True)
    ended_by_user_id = Column(UUID(as_uuid=True), nullable=True)
    
    # Post-session data
    summary_generated = Column(Boolean, default=False, nullable=False)
    feedback_collected = Column(Boolean, default=False, nullable=False)
    
    # Relationships
    # match = relationship("Match", back_populates="session")
    # messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    # user1 = relationship("User", foreign_keys=[user1_id])
    # user2 = relationship("User", foreign_keys=[user2_id])
    
    # Indexes for performance
    __table_args__ = (
        Index('ix_session_users', 'user1_id', 'user2_id'),
        Index('ix_session_state_activity', 'state', 'last_activity_at'),
        Index('ix_session_started_at', 'started_at'),
        Index('ix_session_room_id', 'room_id'),
    )
    
    def __repr__(self):
        return f"<Session(id={self.id}, room_id={self.room_id}, state={self.state})>"
    
    @property
    def is_active(self) -> bool:
        """Check if session is currently active"""
        return self.state == SessionState.ACTIVE
    
    @property
    def is_ended(self) -> bool:
        """Check if session has ended"""
        return self.state in [SessionState.ENDED, SessionState.DROPPED, SessionState.EXPIRED]
    
    @property
    def duration_minutes(self) -> float:
        """Get total session duration in minutes"""
        return self.active_duration_seconds / 60.0
    
    @property
    def is_overdue(self) -> bool:
        """Check if session has exceeded planned duration"""
        if self.is_ended:
            return False
        
        elapsed = datetime.utcnow() - self.started_at
        return elapsed.total_seconds() > (self.planned_duration_minutes * 60)
    
    @property
    def time_remaining_minutes(self) -> float:
        """Get remaining time in minutes"""
        if self.is_ended:
            return 0.0
        
        elapsed = datetime.utcnow() - self.started_at
        elapsed_minutes = elapsed.total_seconds() / 60.0
        return max(0.0, self.planned_duration_minutes - elapsed_minutes)
    
    @property
    def is_idle(self) -> bool:
        """Check if session has been idle too long"""
        if not self.last_activity_at or self.is_ended:
            return False
        
        idle_threshold = timedelta(minutes=15)  # From settings.SESSION_IDLE_TIMEOUT_MINUTES
        return datetime.utcnow() - self.last_activity_at > idle_threshold
    
    def get_partner_id(self, user_id: uuid.UUID) -> uuid.UUID:
        """Get partner's user ID"""
        if user_id == self.user1_id:
            return self.user2_id
        elif user_id == self.user2_id:
            return self.user1_id
        else:
            raise ValueError("User ID not found in this session")
    
    def is_participant(self, user_id: uuid.UUID) -> bool:
        """Check if user is a participant in this session"""
        return user_id in [self.user1_id, self.user2_id]
    
    def update_activity(self, user_id: Optional[uuid.UUID] = None):
        """Update last activity timestamp"""
        now = datetime.utcnow()
        self.last_activity_at = now
        
        if user_id:
            if user_id == self.user1_id:
                self.user1_last_seen = now
            elif user_id == self.user2_id:
                self.user2_last_seen = now
    
    def increment_message_count(self, user_id: uuid.UUID):
        """Increment message count for user"""
        self.total_messages += 1
        
        if user_id == self.user1_id:
            self.user1_message_count += 1
        elif user_id == self.user2_id:
            self.user2_message_count += 1
    
    def set_typing_status(self, user_id: uuid.UUID, is_typing: bool):
        """Set typing status for user"""
        if user_id == self.user1_id:
            self.user1_typing = is_typing
        elif user_id == self.user2_id:
            self.user2_typing = is_typing
        
        if is_typing:
            self.update_activity(user_id)
    
    def switch_turn_language(self) -> TurnLanguage:
        """Switch the current turn language"""
        now = datetime.utcnow()
        
        if self.current_turn_language == TurnLanguage.USER1_NATIVE:
            self.current_turn_language = TurnLanguage.USER2_NATIVE
        elif self.current_turn_language == TurnLanguage.USER2_NATIVE:
            self.current_turn_language = TurnLanguage.USER1_NATIVE
        else:  # MIXED
            # Rotate between user1 and user2 native languages
            self.current_turn_language = TurnLanguage.USER1_NATIVE
        
        self.turn_switched_at = now
        self.turn_switch_count += 1
        
        return self.current_turn_language
    
    def should_suggest_turn_switch(self) -> bool:
        """Check if it's time to suggest language turn switch"""
        if not self.auto_turn_switch_enabled or not self.turn_switched_at:
            return False
        
        # Suggest switch every 10 minutes (from settings.SESSION_TURN_SWITCH_MINUTES)
        switch_interval = timedelta(minutes=10)
        return datetime.utcnow() - self.turn_switched_at > switch_interval
    
    def pause_session(self, reason: str = "disconnection"):
        """Pause the session"""
        if self.state == SessionState.ACTIVE:
            now = datetime.utcnow()
            
            # Update active duration
            if self.paused_at is None:
                active_time = now - self.started_at
                self.active_duration_seconds += int(active_time.total_seconds())
            
            self.state = SessionState.PAUSED
            self.paused_at = now
    
    def resume_session(self):
        """Resume a paused session"""
        if self.state == SessionState.PAUSED and self.paused_at:
            now = datetime.utcnow()
            
            # Update paused duration
            paused_time = now - self.paused_at
            self.paused_duration_seconds += int(paused_time.total_seconds())
            
            self.state = SessionState.ACTIVE
            self.paused_at = None
            self.update_activity()
    
    def end_session(self, reason: SessionEndReason, ended_by_user_id: Optional[uuid.UUID] = None):
        """End the session"""
        if self.is_ended:
            return
        
        now = datetime.utcnow()
        
        # Calculate final active duration
        if self.state == SessionState.ACTIVE:
            active_time = now - (self.paused_at or self.started_at)
            self.active_duration_seconds += int(active_time.total_seconds())
        elif self.state == SessionState.PAUSED and self.paused_at:
            paused_time = now - self.paused_at
            self.paused_duration_seconds += int(paused_time.total_seconds())
        
        # Set end state
        if reason == SessionEndReason.COMPLETED:
            self.state = SessionState.ENDED
        elif reason == SessionEndReason.MAXIMUM_DURATION:
            self.state = SessionState.EXPIRED
        else:
            self.state = SessionState.DROPPED
        
        self.ended_at = now
        self.end_reason = reason
        self.ended_by_user_id = ended_by_user_id
        
        # Clear typing status
        self.user1_typing = False
        self.user2_typing = False
    
    def add_moderation_flag(self, flag_type: str, details: Dict):
        """Add moderation flag to session"""
        if self.moderation_flags is None:
            self.moderation_flags = []
        
        flag = {
            "type": flag_type,
            "timestamp": datetime.utcnow().isoformat(),
            "details": details
        }
        self.moderation_flags.append(flag)
        
        if flag_type in ["toxicity", "inappropriate_content"]:
            self.toxicity_warnings += 1
    
    def get_language_for_user(self, user_id: uuid.UUID) -> str:
        """Get the language this user should be speaking"""
        languages = self.languages or {}
        
        if self.current_turn_language == TurnLanguage.USER1_NATIVE:
            return languages.get("user1_native", languages.get("primary", "en"))
        elif self.current_turn_language == TurnLanguage.USER2_NATIVE:
            return languages.get("user2_native", languages.get("secondary", "en"))
        else:  # MIXED
            return languages.get("primary", "en")
    
    def get_current_prompt(self) -> Optional[str]:
        """Get current conversation prompt"""
        if not self.prompts_used or self.current_prompt_index >= len(self.prompts_used):
            return None
        return self.prompts_used[self.current_prompt_index]
    
    def advance_prompt(self):
        """Move to next conversation prompt"""
        if self.prompts_used and self.current_prompt_index < len(self.prompts_used) - 1:
            self.current_prompt_index += 1
    
    def get_session_stats(self) -> Dict:
        """Get session statistics"""
        return {
            "total_messages": self.total_messages,
            "user1_messages": self.user1_message_count,
            "user2_messages": self.user2_message_count,
            "duration_minutes": self.duration_minutes,
            "active_duration_minutes": self.active_duration_seconds / 60.0,
            "paused_duration_minutes": self.paused_duration_seconds / 60.0,
            "turn_switches": self.turn_switch_count,
            "toxicity_warnings": self.toxicity_warnings,
            "prompts_used_count": len(self.prompts_used or []),
        }
    
    def to_dict(self, current_user_id: Optional[uuid.UUID] = None) -> Dict:
        """Convert session to dictionary"""
        data = {
            "id": str(self.id),
            "room_id": self.room_id,
            "state": self.state.value,
            "languages": self.languages,
            "current_turn_language": self.current_turn_language.value,
            "planned_duration_minutes": self.planned_duration_minutes,
            "started_at": self.started_at.isoformat(),
            "last_activity_at": self.last_activity_at.isoformat() if self.last_activity_at else None,
            "stats": self.get_session_stats(),
            "is_active": self.is_active,
            "is_ended": self.is_ended,
            "time_remaining_minutes": self.time_remaining_minutes,
            "should_suggest_turn_switch": self.should_suggest_turn_switch(),
        }
        
        if current_user_id:
            # Add user-specific information
            partner_id = self.get_partner_id(current_user_id)
            is_user1 = current_user_id == self.user1_id
            
            data.update({
                "partner_id": str(partner_id),
                "your_typing": self.user1_typing if is_user1 else self.user2_typing,
                "partner_typing": self.user2_typing if is_user1 else self.user1_typing,
                "your_message_count": self.user1_message_count if is_user1 else self.user2_message_count,
                "partner_message_count": self.user2_message_count if is_user1 else self.user1_message_count,
                "current_language": self.get_language_for_user(current_user_id),
            })
        else:
            # Include all participant information
            data.update({
                "user1_id": str(self.user1_id),
                "user2_id": str(self.user2_id),
                "user1_typing": self.user1_typing,
                "user2_typing": self.user2_typing,
                "user1_last_seen": self.user1_last_seen.isoformat() if self.user1_last_seen else None,
                "user2_last_seen": self.user2_last_seen.isoformat() if self.user2_last_seen else None,
            })
        
        if self.ended_at:
            data["ended_at"] = self.ended_at.isoformat()
        if self.end_reason:
            data["end_reason"] = self.end_reason.value
        if self.ended_by_user_id:
            data["ended_by_user_id"] = str(self.ended_by_user_id)
        if self.turn_switched_at:
            data["turn_switched_at"] = self.turn_switched_at.isoformat()
        if self.current_prompt_index is not None:
            data["current_prompt"] = self.get_current_prompt()
        
        return data


class SessionMetrics(Base):
    """Session metrics for analytics and improvement"""
    __tablename__ = "session_metrics"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), 
                        nullable=False, unique=True, index=True)
    
    # Engagement metrics
    message_response_times = Column(JSON, nullable=False, default=[])  # List of response times in seconds
    silence_periods = Column(JSON, nullable=False, default=[])  # List of silence durations
    typing_patterns = Column(JSON, nullable=False, default={})  # Typing behavior analysis
    
    # Language learning metrics
    vocabulary_encounters = Column(JSON, nullable=False, default=[])  # New words encountered
    correction_instances = Column(JSON, nullable=False, default=[])  # Language corrections made
    translation_requests = Column(JSON, nullable=False, default=[])  # Translation assistance used
    
    # Quality metrics
    conversation_flow_score = Column(Float, nullable=True)  # 0-1 score of conversation quality
    language_balance_score = Column(Float, nullable=True)  # How balanced the language practice was
    engagement_score = Column(Float, nullable=True)  # Overall engagement level
    
    # Technical metrics
    connection_issues = Column(Integer, default=0, nullable=False)
    reconnection_count = Column(Integer, default=0, nullable=False)
    message_delivery_failures = Column(Integer, default=0, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    def __repr__(self):
        return f"<SessionMetrics(id={self.id}, session_id={self.session_id})>"