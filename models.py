import uuid
from sqlalchemy import Column, String, Text
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector
from database import Base

class LessonChunk(Base):
    __tablename__ = "lesson_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id = Column(String, nullable=False, index=True)
    chunk_type = Column(String, nullable=False)  # 'text' or 'image_description'
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=False)

    def __repr__(self) -> str:
        return f"<LessonChunk(id={self.id}, lesson_id='{self.lesson_id}', chunk_type='{self.chunk_type}')>"
