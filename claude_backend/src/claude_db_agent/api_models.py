"""API request/response models."""

from typing import List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field


class Message(BaseModel):
    """Chat message."""
    role: str = Field(..., description="Role: 'user' or 'model'")
    text: str = Field(..., description="Message text")


class AgentStreamRequest(BaseModel):
    """Request for agent streaming endpoint."""
    message: str = Field(..., description="User message")
    chat_id: str = Field(..., description="Chat ID")
    history: Optional[List[Message]] = Field(default=None, description="Conversation history (deprecated, not used)")


class ChatResponse(BaseModel):
    """Chat metadata response."""
    id: str
    user_id: str
    title: Optional[str]
    created_at: datetime
    updated_at: datetime
    latest_sql: Optional[str] = None
    context_used_chars: int = 0
    context_cap_chars: int = 40000
    context_usage_pct: int = 0
    context_updated_at: Optional[datetime] = None


class ChatListResponse(BaseModel):
    """List of chats response."""
    chats: List[ChatResponse]


class ExecuteSQLRequest(BaseModel):
    """Request for SQL execution endpoint."""
    projectRef: str = Field(..., description="Supabase project reference ID")
    accessToken: str = Field(..., description="Supabase Management API access token")
    query: str = Field(..., description="SQL query to execute")


class ExecuteSQLResponse(BaseModel):
    """Response from SQL execution endpoint."""
    success: bool = Field(..., description="Whether execution succeeded")
    message: str = Field(..., description="Status message")
    data: Optional[Any] = Field(default=None, description="Response data from Supabase")


class MemoryQARequest(BaseModel):
    """Request to save a clarification Q&A entry."""
    chat_id: str = Field(..., description="Chat ID")
    question: str = Field(..., description="Clarification question")
    answer: str = Field(..., description="User answer")


class MemoryQAItem(BaseModel):
    """Clarification Q&A item."""
    content: str = Field(..., description="Q&A content")


class MemoryQAListResponse(BaseModel):
    """List of clarification Q&A entries."""
    items: List[MemoryQAItem]
