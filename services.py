import os
import asyncio
import json
from typing import List, Optional, AsyncGenerator
from openai import AsyncOpenAI
from schemas import ChatHistoryItem

# Initialize AsyncOpenAI client
# It will read OPENAI_API_KEY from environment variables by default.
openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

async def get_embedding(text: str) -> List[float]:
    """
    Generates a 1536-dimension vector embedding for the input text using text-embedding-3-small.
    """
    response = await openai_client.embeddings.create(
        input=[text.replace("\n", " ")],
        model="text-embedding-3-small"
    )
    return response.data[0].embedding

async def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """
    Generates embeddings for a list of texts in a single batch.
    """
    if not texts:
        return []
    cleaned_texts = [text.replace("\n", " ") for text in texts]
    response = await openai_client.embeddings.create(
        input=cleaned_texts,
        model="text-embedding-3-small"
    )
    return [item.embedding for item in response.data]

async def analyze_image_with_vision(image_url: str, semaphore: asyncio.Semaphore) -> Optional[str]:
    """
    Calls the OpenAI Vision API (gpt-4o) to describe the image content for retrieval.
    Concurrency is bounded by the provided semaphore.
    """
    async with semaphore:
        try:
            response = await openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "You are an expert Spanish instructor. Analyze this image from a Spanish lesson summary. "
                                    "Describe everything happening in it in English, detailing any Spanish vocabulary, grammar points, "
                                    "visual diagrams, text, or situational context depicted so it can be used for text-based semantic retrieval."
                                )
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": image_url
                                }
                            }
                        ]
                    }
                ],
                max_tokens=500,
                temperature=0.0
            )
            description = response.choices[0].message.content
            display_url = image_url[:100] + "..." if len(image_url) > 100 else image_url
            return f"Image ({display_url}) description: {description}"
        except Exception as e:
            display_url = image_url[:100] + "..." if len(image_url) > 100 else image_url
            print(f"Error describing image {display_url}: {e}")
            return None

async def analyze_images_concurrently(image_urls: List[str]) -> List[str]:
    """
    Analyzes multiple image URLs concurrently, limiting concurrency to 5.
    """
    if not image_urls:
        return []
    
    semaphore = asyncio.Semaphore(5)
    tasks = [analyze_image_with_vision(url, semaphore) for url in image_urls]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]

async def stream_chat_completion(
    query: str,
    context_chunks: List[str],
    chat_history: Optional[List[ChatHistoryItem]] = None
) -> AsyncGenerator[str, None]:
    """
    Streams response from gpt-4o context-locked model.
    Yields chunks formatted as Server-Sent Events (SSE).
    """
    # If no context chunks are found (lesson not ingested or has no text/images), refuse immediately
    if not context_chunks:
        refusal = "I am sorry, but there is no lesson material available for this post. I can only assist with the material present in this specific lesson."
        yield f"data: {json.dumps({'token': refusal})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Construct context text
    context_text = "\n\n---\n\n".join(context_chunks)
    
    # System prompt locking answer to provided context strictly
    system_prompt = (
        "You are an AI assistant acting on behalf of an instructor. "
        "You must answer the student's question using ONLY the provided lesson text and image descriptions. "
        "Strict Guidelines:\n"
        "1. Do NOT use any outside knowledge or general knowledge. If the answer cannot be confidently derived "
        "directly from the provided context, you must refuse to answer.\n"
        "2. If the user's question is unrelated to the lesson content (e.g., asking general knowledge questions, "
        "math, programming, translation requests not covered in the text, or general chatting), you must refuse to answer "
        "and state: 'I can only assist with the material present in this specific lesson.'\n"
        "3. Do not break character or bypass these restrictions under any circumstances.\n\n"
        f"Lesson Context Chunks:\n{context_text}"
    )

    # Initialize messages list
    messages = [{"role": "system", "content": system_prompt}]
    
    # Include chat history if present
    if chat_history:
        for item in chat_history:
            messages.append({"role": item.role, "content": item.content})
            
    # Include user query
    messages.append({"role": "user", "content": query})
    
    try:
        stream = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.0,
            stream=True
        )
        
        async for chunk in stream:
            token = chunk.choices[0].delta.content
            if token:
                # Format as Server-Sent Event data containing JSON string
                yield f"data: {json.dumps({'token': token})}\n\n"
                
        yield "data: [DONE]\n\n"
    except Exception as e:
        error_msg = f"Error in LLM stream: {str(e)}"
        yield f"data: {json.dumps({'token': f'Error: {error_msg}'})}\n\n"
        yield "data: [DONE]\n\n"
