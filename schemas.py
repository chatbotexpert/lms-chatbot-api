from typing import List, Optional
from pydantic import BaseModel, Field

class IngestPayload(BaseModel):
    lesson_id: str = Field(..., description="Raw WordPress post ID, e.g., '2980'")
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

class SimpleChatPayload(BaseModel):
    message: str = Field(..., description="The user's test message")

class SimpleChatResponse(BaseModel):
    response: str

class BatchIngestPayload(BaseModel):
    records: List[IngestPayload] = Field(..., description="List of lesson payloads to ingest in batch")

class BatchIngestResponse(BaseModel):
    success: bool
    message: str
    processed_count: int
    chunks_created: int
    errors: List[str] = Field(default_factory=list, description="Errors encountered during batch processing")

