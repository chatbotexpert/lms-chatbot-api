import os
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Security, status, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, delete, select
from langchain_text_splitters import RecursiveCharacterTextSplitter

from database import engine, Base, get_db, AsyncSessionLocal
from models import LessonChunk
from schemas import (
    IngestPayload, 
    ChatPayload, 
    IngestResponse, 
    SimpleChatPayload
)
from services import (
    get_embedding,
    get_embeddings_batch,
    analyze_images_concurrently,
    stream_chat_completion
)

# ---------------------------------------------------------
# Database Initialization Lifespan Hook
# ---------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    async with engine.begin() as conn:
        # Create the pgvector extension if it doesn't already exist.
        # This requires appropriate privileges on the database.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        # Create all database tables
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown logic: clean up engine connections
    await engine.dispose()

# ---------------------------------------------------------
# FastAPI App Instance
# ---------------------------------------------------------
app = FastAPI(
    title="LMS RAG Chatbot API", 
    description="Context-locked, PostgreSQL/pgvector-powered chatbot backend for WordPress Spanish learning platform.",
    version="2.0.0",
    lifespan=lifespan
)

# ---------------------------------------------------------
# CORS Configuration
# ---------------------------------------------------------
# Allowed origins can be specified as a comma-separated list in ALLOWED_ORIGINS env var
origins_str = os.getenv("ALLOWED_ORIGINS", "*")
origins = [origin.strip() for origin in origins_str.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True if origins_str != "*" else False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Security Dependency
# ---------------------------------------------------------
# We accept the key via either X-API-Key header or Authorization: Bearer <key> header
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_token = HTTPBearer(auto_error=False)

async def verify_api_key(
    api_key: Optional[str] = Security(api_key_header),
    auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_token)
):
    expected_key = os.getenv("LMS_API_KEY")
    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API Key security configuration (LMS_API_KEY) is missing on the server."
        )
    
    token = None
    if api_key:
        token = api_key
    elif auth:
        token = auth.credentials
        
    if not token or token != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key."
        )

# ---------------------------------------------------------
# Endpoints
# ---------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <html>
        <head>
            <title>LMS RAG Chatbot Backend</title>
            <style>
                body { font-family: 'Outfit', sans-serif; background-color: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
                .card { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 16px; padding: 2.5rem; max-width: 500px; text-align: center; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3); }
                h1 { color: #38bdf8; margin-top: 0; font-size: 2rem; font-weight: 700; background: linear-gradient(to right, #38bdf8, #818cf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
                p { color: #94a3b8; font-size: 1rem; line-height: 1.5; }
                .badge { display: inline-block; background-color: #1e293b; color: #38bdf8; padding: 0.25rem 0.75rem; border-radius: 9999px; font-weight: 500; font-size: 0.875rem; margin-top: 1rem; border: 1px solid rgba(56, 189, 248, 0.2); }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>LMS RAG Chatbot Service</h1>
                <p>Welcome! The high-performance context-locked vector backend is running successfully with PostgreSQL and pgvector.</p>
                <div class="badge">V2.0.0 Active</div>
            </div>
        </body>
    </html>
    """


# Create a global semaphore to process only 1 background task at a time
INGEST_SEMAPHORE = asyncio.Semaphore(1)

async def process_images_in_background(lesson_id: str, image_urls: list[str]):
    """
    Downloads and analyzes images, generates their vector embeddings, and stores
    them in the database in the background.
    """
    if not image_urls:
        return

    async with INGEST_SEMAPHORE:
        print(f"Background task started: processing {len(image_urls)} images for lesson '{lesson_id}'...")

        # 1. Fetch and describe images in the background (using vision or LLM SVG text analysis)
        image_descriptions = await analyze_images_concurrently(image_urls)
        if not image_descriptions:
            print(f"Background task complete: No valid image descriptions generated for lesson '{lesson_id}'.")
            return

        # 2. Generate embeddings in batch for descriptions
        try:
            embeddings = await get_embeddings_batch(image_descriptions)
        except Exception as e:
            print(f"Background task failed: Embedding generation for image descriptions failed for lesson '{lesson_id}': {e}")
            return

        # 3. Open dedicated session and persist to database
        async with AsyncSessionLocal() as db:
            new_chunks = []
            for j, desc in enumerate(image_descriptions):
                new_chunks.append(
                    LessonChunk(
                        lesson_id=lesson_id,
                        chunk_type="image_description",
                        content=desc,
                        embedding=embeddings[j]
                    )
                )

            try:
                db.add_all(new_chunks)
                await db.commit()
                print(f"Background task complete: successfully indexed {len(new_chunks)} image descriptions for lesson '{lesson_id}'.")
            except Exception as e:
                await db.rollback()
                print(f"Background task failed: failed to save image description chunks to database for lesson '{lesson_id}': {e}")


@app.post("/api/ingest", response_model=IngestResponse)
async def ingest(
    payload: IngestPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_api_key)
):
    """
    Endpoint 1: Ingests lesson content synchronously, and queues image analysis in background.
    """
    # 1. Idempotency: Delete previous entries matching the incoming lesson_id
    try:
        await db.execute(delete(LessonChunk).where(LessonChunk.lesson_id == payload.lesson_id))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database synchronization error: {str(e)}"
        )

    # 2. Dynamic Chunking: Split text content (approx 1,000 chars, 200 overlap)
    text_chunks = []
    if payload.content and payload.content.strip():
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        text_chunks = splitter.split_text(payload.content)

    if not text_chunks and not payload.image_urls:
        return IngestResponse(
            success=True,
            message="No text content or image URLs found to index.",
            chunks_created=0
        )

    # 3. Synchronously Vectorize and Save Text Chunks (if any)
    new_chunks = []
    if text_chunks:
        try:
            embeddings = await get_embeddings_batch(text_chunks)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Embedding generation for text failed: {str(e)}"
            )

        for i, chunk in enumerate(text_chunks):
            new_chunks.append(
                LessonChunk(
                    lesson_id=payload.lesson_id,
                    chunk_type="text",
                    content=chunk,
                    embedding=embeddings[i]
                )
            )

        try:
            db.add_all(new_chunks)
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to persist lesson text chunks to database: {str(e)}"
            )

    # 4. Offload Image Analysis to Background Tasks
    if payload.image_urls:
        background_tasks.add_task(
            process_images_in_background,
            payload.lesson_id,
            payload.image_urls
        )

    msg = f"Successfully ingested lesson '{payload.lesson_id}' with {len(text_chunks)} text chunks."
    if payload.image_urls:
        msg += f" Queued {len(payload.image_urls)} images for background analysis."

    return IngestResponse(
        success=True,
        message=msg,
        chunks_created=len(new_chunks)
    )


@app.post("/api/ingest/sync", response_model=IngestResponse)
async def ingest_sync(
    payload: IngestPayload,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_api_key)
):
    """
    Endpoint 1a: Ingests lesson content and processes image analysis synchronously (no background tasks).
    """
    # 1. Idempotency: Delete previous entries matching the incoming lesson_id
    try:
        await db.execute(delete(LessonChunk).where(LessonChunk.lesson_id == payload.lesson_id))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database synchronization error: {str(e)}"
        )

    # 2. Dynamic Chunking: Split text content (approx 1,000 chars, 200 overlap)
    text_chunks = []
    if payload.content and payload.content.strip():
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        text_chunks = splitter.split_text(payload.content)

    if not text_chunks and not payload.image_urls:
        return IngestResponse(
            success=True,
            message="No text content or image URLs found to index.",
            chunks_created=0
        )

    # 3. Synchronously Vectorize and Prepare Text Chunks (if any)
    new_chunks = []
    if text_chunks:
        try:
            embeddings = await get_embeddings_batch(text_chunks)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Embedding generation for text failed: {str(e)}"
            )

        for i, chunk in enumerate(text_chunks):
            new_chunks.append(
                LessonChunk(
                    lesson_id=payload.lesson_id,
                    chunk_type="text",
                    content=chunk,
                    embedding=embeddings[i]
                )
            )
        db.add_all(new_chunks)

    # 4. Synchronously Process and Vectorize Images (if any)
    image_chunks_count = 0
    if payload.image_urls:
        try:
            image_descriptions = await analyze_images_concurrently(payload.image_urls)
            if image_descriptions:
                img_embeddings = await get_embeddings_batch(image_descriptions)
                img_chunks = []
                for j, desc in enumerate(image_descriptions):
                    img_chunks.append(
                        LessonChunk(
                            lesson_id=payload.lesson_id,
                            chunk_type="image_description",
                            content=desc,
                            embedding=img_embeddings[j]
                        )
                    )
                db.add_all(img_chunks)
                image_chunks_count = len(img_chunks)
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Image processing or embedding generation failed: {str(e)}"
            )

    # Commit all chunks (text + images) at the end
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist lesson chunks to database: {str(e)}"
        )

    msg = f"Successfully ingested lesson '{payload.lesson_id}' with {len(text_chunks)} text chunks"
    if image_chunks_count > 0:
        msg += f" and {image_chunks_count} image descriptions synchronously."
    else:
        msg += "."

    return IngestResponse(
        success=True,
        message=msg,
        chunks_created=len(new_chunks) + image_chunks_count
    )


@app.post("/api/test")
async def ingest_test(payload: IngestPayload):
    """
    Debug endpoint: echoes back exactly what was received from WordPress.
    No auth required. Returns a breakdown so you can verify the data format
    without digging through Vercel logs.
    """
    print(payload)
    return {
        "received": payload
    }

@app.post("/api/chat")
async def chat(
    payload: ChatPayload,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_api_key)
):
    """
    Endpoint 2: Context-Locked RAG Chat with Server-Sent Events (SSE) Streaming.
    Generates query embedding, performs strict metadata filtering, and streams gpt-4o-mini response.
    """
    # 1. Generate vector embedding for user query
    try:
        query_vector = await get_embedding(payload.message)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate query embedding: {str(e)}"
        )

    # 2. Unified pgvector Cosine Similarity Query
    # Retrieves the top 5 closest matching chunks (both text and image descriptions) for the lesson.
    try:
        stmt = (
            select(LessonChunk)
            .where(LessonChunk.lesson_id == payload.lesson_id)
            .order_by(LessonChunk.embedding.cosine_distance(query_vector))
            .limit(5)
        )
        result = await db.execute(stmt)
        matched_chunks = list(result.scalars().all())
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database similarity query failed: {str(e)}"
        )

    # Extract content from retrieved contexts
    context_chunks = [chunk.content for chunk in matched_chunks]

    # 3. Stream Response via SSE
    return StreamingResponse(
        stream_chat_completion(
            query=payload.message,
            context_chunks=context_chunks,
            chat_history=payload.chat_history
        ),
        media_type="text/event-stream"
    )

if __name__ == "__main__":
    import uvicorn
    # Start uvicorn server on port 7000
    uvicorn.run("main:app", host="0.0.0.0", port=7000, reload=True)


