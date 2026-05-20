from typing import List, Optional
from pydantic import BaseModel, Field

class IngestPayload(BaseModel):
    lesson_id: str = Field(..., description="ID of the WordPress lesson, e.g., 'lesson_123'")
    instructor_id: str = Field(..., description="ID of the instructor, e.g., 'instructor_4'")
    content: str = Field(..., description="The main text content of the lesson")
    image_urls: List[str] = Field(default_factory=list, description="URLs of images in the lesson to parse with vision model")

class ChatHistoryItem(BaseModel):
    role: str = Field(..., description="Role of the message author: 'system', 'user', or 'assistant'")
    content: str = Field(..., description="The text content of the message")

class ChatPayload(BaseModel):
    lesson_id: str = Field(..., description="ID of the WordPress lesson to query context from")
    message: str = Field(..., description="The student's question/query")
    chat_history: Optional[List[ChatHistoryItem]] = Field(default=None, description="Optional conversation history for context")

class IngestResponse(BaseModel):
    success: bool
    message: str
    chunks_created: int
