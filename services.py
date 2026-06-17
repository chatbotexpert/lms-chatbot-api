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

async def analyze_image_with_vision(image_url: str, index: int, semaphore: asyncio.Semaphore) -> Optional[str]:
    """
    Calls the OpenAI Vision API (gpt-4o-mini) to describe the image content for retrieval.
    Concurrency is bounded by the provided semaphore, with exponential backoff retries for rate limits.
    """
    async with semaphore:
        max_retries = 10
        backoff_base = 2.0
        for attempt in range(max_retries):
            try:
                response = await openai_client.chat.completions.create(
                    model="gpt-4o-mini",
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
                return f"Image #{index} description: {description}"
            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = "rate_limit" in err_str or "429" in err_str or "rate limit" in err_str
                
                if is_rate_limit and attempt < max_retries - 1:
                    import random
                    sleep_time = backoff_base * (2 ** attempt) + random.uniform(0.5, 2.5)
                    print(f"Rate limit (429) hit for image #{index}. Retrying in {sleep_time:.2f}s (Attempt {attempt+1}/{max_retries})...")
                    await asyncio.sleep(sleep_time)
                else:
                    print(f"Error describing image #{index}: {e}")
                    return None

async def analyze_images_concurrently(image_urls: List[str]) -> List[str]:
    """
    Analyzes multiple image URLs concurrently, limiting concurrency to 5.
    """
    if not image_urls:
        return []
    
    semaphore = asyncio.Semaphore(2)
    tasks = [analyze_image_with_vision(url, i + 1, semaphore) for i, url in enumerate(image_urls)]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]

async def stream_chat_completion(
    query: str,
    context_chunks: List[str],
    chat_history: Optional[List[ChatHistoryItem]] = None
) -> AsyncGenerator[str, None]:
    """
    Streams response from gpt-4o-mini context-locked model.
    Yields chunks formatted as Server-Sent Events (SSE).
    """
    # If no context chunks are found (lesson not ingested or has no text/images), refuse immediately
    if not context_chunks:
        refusal = (
            "Lo siento, pero no hay material de lección disponible para esta publicación. Solo puedo asistir con el material presente en esta lección específica.\n\n"
            "I am sorry, but there is no lesson material available for this post. I can only assist with the material present in this specific lesson."
        )
        yield f"data: {json.dumps({'token': refusal})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Construct context text
    context_text = "\n\n---\n\n".join(context_chunks)
    
    # System prompt locking answer to provided context strictly but encouraging pedagogical depth
    system_prompt = (
        "You are a friendly and helpful AI assistant acting on behalf of an expert Spanish instructor. "
        "Your goal is to answer the student's question thoroughly using the provided lesson text and image descriptions. "
        "Guidelines for Your Response:\n"
        "1. MANDATORY Bilingual Response: You MUST ALWAYS write EVERY content answer in BOTH Spanish AND English — NO EXCEPTIONS. "
        "You MUST use this exact structure for every content response:\n"
        "🇪🇸 **En Español:**\n[Your full answer written in Spanish]\n\n"
        "🇬🇧 **In English:**\n[Your full answer written in English]\n\n"
        "NEVER skip the English section. NEVER respond only in Spanish. NEVER respond only in English. "
        "Both language sections are REQUIRED for every single content response.\n"
        "2. Translation on Demand: If the user requests to translate text from Spanish to English or from English to Spanish, you must perform the translation as requested.\n"
        "3. Comprehensive Coverage: Extract and explain all relative details, concepts, vocabulary, and grammar points "
        "found in the provided context that pertain to the student's query. Do not leave out any relevant details.\n"
        "4. Concept Elaboration: Proactively introduce and explain any related concepts, examples, or structural points "
        "that are discussed in the same section of the lesson, helping the student see the full picture and connect concepts.\n"
        "5. Strict Context Boundary: When answering content questions, you must answer using ONLY information that is present in or can be directly derived "
        "from the provided context. Do NOT use outside general knowledge or introduce vocabulary/grammar rules not mentioned "
        "in the lesson. If the answer cannot be confidently derived from the context, refuse to answer. "
        "However, if the student makes a minor factual slip or phrasing error about context roles (e.g., asking about an email 'sent to' Raquel Azcona when the context has an email 'sent by' Raquel Azcona to Rocío), do NOT refuse. Gently correct the student's premise based on the context and proceed to answer the question thoroughly.\n"
        "6. Friendly Greetings & Small Talk: If the student greets you (e.g., 'hello', 'hi', 'hola', 'good morning', 'how are you'), "
        "respond warmly and in a friendly manner. Greet them back, let them know you are here to help with this lesson, "
        "and invite them to ask their questions. You may respond to brief conversational messages naturally. "
        "For greetings only, a short response is fine — no need for the full bilingual format.\n"
        "7. Strict Refusal Policy: If the student's question is a content question completely unrelated to the lesson "
        "(and is not a translation request, greeting, or small talk), you must refuse to answer "
        "and state (first in Spanish, then in English): 'Solo puedo ayudar con el material de esta lección específica. / I can only assist with the material present in this specific lesson.'\n"
        "8. Readability & Structure: Format your response beautifully using clear headings, bullet points, and numbered lists to "
        "structure the explanation logically. Use bold text to highlight key Spanish words or rules.\n\n"
        f"Lesson Context Chunks:\n{context_text}"
    )

    # Initialize messages list
    messages = [{"role": "system", "content": system_prompt}]
    
    # Include chat history if present (limit to last 6 messages to cap token cost)
    if chat_history:
        for item in chat_history[-6:]:
            messages.append({"role": item.role, "content": item.content})
            
    # Include user query
    messages.append({"role": "user", "content": query})
    
    try:
        stream = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
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
