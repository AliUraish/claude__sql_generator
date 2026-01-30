"""FastAPI application for Claude DB Agent."""

import os
import json
import re
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from anthropic import Anthropic
import httpx

from .api_models import (
    AgentStreamRequest, 
    ExecuteSQLRequest, 
    ExecuteSQLResponse,
    ChatResponse,
    ChatListResponse
)
from .neon_db import NeonDB
from .clerk_auth import require_user_id

# Load environment variables
load_dotenv()

# System instruction for Claude (matching frontend UX)
SYSTEM_INSTRUCTION = """You are a world-class database architect and SQL expert specializing in Supabase (PostgreSQL).
Your task is to help users design and generate SQL schemas.

Tool Use Policy:
1. Only request tools when strictly necessary to complete the user's request.
2. Prefer answering from existing context; do NOT call tools by default.
3. Ask for clarification instead of calling tools if requirements are unclear.

Strict Output Format:
1. Always provide a brief explanation of what you are building in plain text.
2. Always provide the actual SQL in a standard markdown code block: ```sql ... ```.
3. The UI will automatically hide the code block from the chat and show it in a dedicated editor.
4. DO NOT repeat the code outside the code block.

Database Rules:
1. Always output valid PostgreSQL SQL compatible with Supabase.
2. Adhere to PostgreSQL best practices: use snake_case, include RLS policies, foreign keys, and indexes.
3. Default schema is 'public'. Include 'DROP TABLE IF EXISTS' for clean iterations.
4. Use uppercase for SQL keywords.
5. Include concise comments starting with --."""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Startup
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("⚠️  Warning: ANTHROPIC_API_KEY not set")
    
    # Initialize Neon DB connection pool
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        NeonDB.initialize(database_url)
        print("✓ Neon DB connection pool initialized")
    else:
        print("⚠️  Warning: DATABASE_URL not set, chat persistence disabled")
    
    yield
    
    # Shutdown
    NeonDB.close_pool()


# Create FastAPI app
app = FastAPI(
    title="Claude DB Agent API",
    description="Backend API for Claude-powered database schema generation",
    version="0.1.0",
    lifespan=lifespan
)

# Configure CORS
frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin, "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def extract_sql_blocks(text: str) -> str:
    """Extract SQL from markdown code blocks (handles complete and incomplete blocks)."""
    # Try to find complete SQL block first
    sql_match = re.search(r'```sql\s*([\s\S]*?)```', text, re.IGNORECASE | re.DOTALL)
    if sql_match:
        return sql_match.group(1).strip()
    
    # If no complete block, check for incomplete block (during streaming)
    incomplete_match = re.search(r'```sql\s*([\s\S]*)', text, re.IGNORECASE | re.DOTALL)
    if incomplete_match:
        # Extract everything after ```sql until end of text
        sql_content = incomplete_match.group(1).strip()
        # Remove any trailing markdown if it appears
        sql_content = re.sub(r'```\s*$', '', sql_content).strip()
        return sql_content
    
    return ''


def strip_sql_blocks(text: str) -> str:
    """Remove SQL code blocks from text (including incomplete blocks during streaming).
    
    This ensures SQL never appears in the chat - only explanatory text is shown.
    """
    if not text:
        return ''
    
    # Remove complete SQL blocks (```sql ... ```)
    text = re.sub(r'```sql\s*[\s\S]*?```', '', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Remove incomplete SQL blocks (during streaming: ```sql ... without closing ```)
    text = re.sub(r'```sql[\s\S]*$', '', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Remove standalone opening markdown (```sql) if it appears
    text = re.sub(r'```sql\s*', '', text, flags=re.IGNORECASE)
    
    # Clean up any extra whitespace/newlines left behind
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)  # Multiple newlines -> max 2
    text = text.strip()
    
    return text


def merge_sql_patch(existing_sql: str, patch_sql: str) -> str:
    """Append patch SQL to existing SQL with a separator."""
    existing = (existing_sql or "").strip()
    patch = (patch_sql or "").strip()
    if not existing:
        return patch
    if not patch:
        return existing
    return f"{existing}\n\n-- PATCH APPLIED\n{patch}\n"


def should_use_memory(user_message: str) -> bool:
    """Detect if user is referencing previous context."""
    if not user_message:
        return False
    trigger_pattern = r"\b(previous|earlier|before|above|last time|as i said|as i mentioned|you said|we discussed|prior)\b"
    return re.search(trigger_pattern, user_message, re.IGNORECASE) is not None


def should_use_sql_context(user_message: str) -> bool:
    """Detect if user is asking to create/edit SQL/schema."""
    if not user_message:
        return False
    sql_pattern = r"\b(sql|schema|table|column|index|constraint|rls|policy|alter|create|drop|add|remove|modify|change|update)\b"
    return re.search(sql_pattern, user_message, re.IGNORECASE) is not None


async def generate_sse_stream(request: AgentStreamRequest, user_id: str) -> AsyncGenerator[str, None]:
    """Generate SSE events from Claude streaming response with tool calls and context management."""
    from .sql_tools import (
        get_compact_sql_context,
        get_latest_sql,
        save_new_sql_version,
        update_chat_timestamp,
        get_chat_context_usage,
        update_chat_context_usage
    )
    from .supermemory_client import SupermemoryClient
    
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        yield f"event: error\ndata: {json.dumps({'message': 'ANTHROPIC_API_KEY not configured'})}\n\n"
        return
    
    chat_id = request.chat_id
    
    # Send initial context event from persisted DB values
    supermemory_api_key = os.getenv("SUPERMEMORY_API_KEY")
    persisted_context = await get_chat_context_usage(chat_id)
    if not persisted_context:
        await update_chat_context_usage(chat_id, 0, 40000)
        persisted_context = await get_chat_context_usage(chat_id)
    persisted_used = persisted_context["usedChars"] if persisted_context else 0
    persisted_cap = persisted_context["capChars"] if persisted_context else 40000

    # If Supermemory is available, avoid empty-query searches (unsupported)
    # Persisted context is updated on summary writes instead.

    context_data = {
        'chatId': str(chat_id),
        'usedChars': persisted_used,
        'capChars': persisted_cap,
        'usagePct': int((persisted_used / persisted_cap) * 100) if persisted_cap else 0
    }
    yield f"event: context\ndata: {json.dumps(context_data)}\n\n"
    
    try:
        # Fetch latest SQL for comparison only (no tool event, not in prompt unless needed)
        latest_sql_text = await get_latest_sql(chat_id)

        # Build context block for prompt
        context_parts = []
        has_existing_sql = bool(latest_sql_text and latest_sql_text.strip())

        # SQL context only when relevant
        sql_context_needed = should_use_sql_context(request.message)
        if sql_context_needed:
            yield f"event: tool\ndata: {json.dumps({'name': 'get_compact_sql_context', 'status': 'start'})}\n\n"
            compact_sql = await get_compact_sql_context(chat_id)
            yield f"event: tool\ndata: {json.dumps({'name': 'get_compact_sql_context', 'status': 'done'})}\n\n"
            context_parts.append(f"Latest SQL context (read-only, compact):\n{compact_sql}")
        
        if has_existing_sql:
            context_parts.append(
                "IMPORTANT: An existing schema already exists. "
                "Output ONLY the minimal SQL patch (ALTER/CREATE/DROP) needed to apply the change. "
                "Do NOT repeat the full schema."
            )
        
        # Check if Supermemory is available (optional)
        memory_context_str = ""  # String representation for context block
        memory_chunks_list = []  # List of chunks for later use
        
        if supermemory_api_key and should_use_memory(request.message):
            yield f"event: tool\ndata: {json.dumps({'name': 'get_summary_memory', 'status': 'start'})}\n\n"
            try:
                sm_client = SupermemoryClient(supermemory_api_key)
                memory_chunks_list = await sm_client.search_chat_memory(chat_id, user_id, request.message)
                if memory_chunks_list:
                    memory_context_str = "\n\n".join(memory_chunks_list)
                    context_parts.append(f"\nMemory (from previous conversation):\n{memory_context_str}")
                yield f"event: tool\ndata: {json.dumps({'name': 'get_summary_memory', 'status': 'done'})}\n\n"
            except Exception as e:
                import traceback
                print(f"⚠️  Memory retrieval failed: {e}")
                print(f"⚠️  Traceback: {traceback.format_exc()}")
                yield f"event: tool\ndata: {json.dumps({'name': 'get_summary_memory', 'status': 'error'})}\n\n"
        
        # Build messages (no raw history, just context + current message)
        context_block = "\n\n".join(context_parts)
        user_content = f"User request: {request.message}" if not context_block else f"{context_block}\n\nUser request: {request.message}"
        messages = [{"role": "user", "content": user_content}]
        
        # Initialize Anthropic client
        client = Anthropic(
            api_key=api_key,
            timeout=httpx.Timeout(60.0, connect=10.0),
            max_retries=2
        )
        
        # Stream from Claude
        full_response = ""
        last_sql = ""
        last_clean_text = ""
        
        with client.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
            system=SYSTEM_INSTRUCTION,
            messages=messages,
            temperature=0.3
        ) as stream:
            for text in stream.text_stream:
                full_response += text
                
                # Extract current SQL
                current_sql = extract_sql_blocks(full_response)
                
                # Send SQL event if it changed (SQL goes only to schema output)
                if current_sql and current_sql != last_sql:
                    last_sql = current_sql
                    yield f"event: sql\ndata: {json.dumps({'sql': current_sql})}\n\n"
                
                # Calculate cleaned text (without SQL blocks) for chat
                clean_text = strip_sql_blocks(full_response)
                
                # Only send text delta if cleaned text changed (ensures SQL never appears in chat)
                if clean_text != last_clean_text:
                    # Calculate the actual delta of cleaned text
                    text_delta = clean_text[len(last_clean_text):]
                    if text_delta:  # Only send if there's new text
                        yield f"event: delta\ndata: {json.dumps({'textDelta': text_delta, 'fullText': clean_text})}\n\n"
                    last_clean_text = clean_text
        
        # Send final event
        final_text = strip_sql_blocks(full_response)
        final_sql = extract_sql_blocks(full_response)
        merged_sql = merge_sql_patch(latest_sql_text, final_sql)
        # Send merged SQL to UI to keep full schema in view
        yield f"event: done\ndata: {json.dumps({'finalText': final_text, 'finalSql': merged_sql})}\n\n"
        
        # Persist: Save new SQL version if changed
        if final_sql and final_sql.strip() != latest_sql_text.strip():
            await save_new_sql_version(chat_id, merged_sql)
        
        # Update chat timestamp
        await update_chat_timestamp(chat_id)
        
        # Update Supermemory summary (best-effort)
        if supermemory_api_key:
            try:
                sm_client = SupermemoryClient(supermemory_api_key)
                # Build simple rolling summary: user message + assistant response
                new_summary_chunk = f"User: {request.message}\nAssistant: {final_text}\n\n"
                
                # Use persisted usage for accurate context tracking
                current_summary = memory_context_str if memory_context_str else ""
                base_used = max(persisted_used, len(current_summary))
                would_exceed = (base_used + len(new_summary_chunk)) > sm_client.CONTEXT_CAP_CHARS
                
                if would_exceed:
                    # Create new chat and signal rollover
                    new_chat = await NeonDB.execute_returning(
                        "INSERT INTO chats (user_id, title) VALUES (%s, %s) RETURNING id",
                        (user_id, None)
                    )
                    if not new_chat:
                        raise ValueError("Failed to create new chat during rollover")
                    
                    # Convert UUID to string for JSON serialization
                    new_chat_id = str(new_chat["id"])
                    
                    # Insert initial empty SQL for new chat
                    await NeonDB.execute(
                        "INSERT INTO chat_sql_versions (chat_id, sql_text) VALUES (%s, %s)",
                        (new_chat_id, "")
                    )
                    await update_chat_context_usage(new_chat_id, 0, 40000)
                    
                    # Signal rollover to frontend
                    yield f"event: chat_rollover\ndata: {json.dumps({'newChatId': new_chat_id})}\n\n"
                else:
                    # Update summary normally
                    updated_summary = current_summary + new_summary_chunk
                    new_used_chars = min(
                        base_used + len(new_summary_chunk),
                        sm_client.CONTEXT_CAP_CHARS
                    )
                    await update_chat_context_usage(
                        chat_id,
                        new_used_chars,
                        sm_client.CONTEXT_CAP_CHARS
                    )
                    await sm_client.update_chat_summary(chat_id, user_id, updated_summary)

                    # Recalculate and fetch persisted context after each chat
                    recalculated_context = await get_chat_context_usage(chat_id)
                    if recalculated_context:
                        context_data = {
                            'chatId': str(chat_id),
                            'usedChars': recalculated_context["usedChars"],
                            'capChars': recalculated_context["capChars"],
                            'usagePct': recalculated_context["usagePct"]
                        }
                        yield f"event: context\ndata: {json.dumps(context_data)}\n\n"
            
            except Exception as e:
                import traceback
                print(f"⚠️  Supermemory summary update failed: {e}")
                print(f"⚠️  Traceback: {traceback.format_exc()}")
                # Fallback to persisted context usage
                fallback_context = await get_chat_context_usage(chat_id)
                if fallback_context:
                    yield f"event: context\ndata: {json.dumps({'chatId': str(chat_id), 'usedChars': fallback_context['usedChars'], 'capChars': fallback_context['capChars'], 'usagePct': fallback_context['usagePct']})}\n\n"
        else:
            # Supermemory not configured - send 0% context
            await update_chat_context_usage(chat_id, 0, 40000)
            recalculated_context = await get_chat_context_usage(chat_id)
            context_data = {
                'chatId': str(chat_id),
                'usedChars': recalculated_context["usedChars"] if recalculated_context else 0,
                'capChars': recalculated_context["capChars"] if recalculated_context else 40000,
                'usagePct': recalculated_context["usagePct"] if recalculated_context else 0
            }
            yield f"event: context\ndata: {json.dumps(context_data)}\n\n"
        
    except Exception as e:
        error_msg = str(e)
        yield f"event: error\ndata: {json.dumps({'message': f'Error: {error_msg}'})}\n\n"


@app.post("/api/chats/new", response_model=ChatResponse)
async def create_new_chat(user_id: str = Depends(require_user_id)):
    """Create a new chat for the authenticated user."""
    try:
        from .sql_tools import update_chat_context_usage
        # Upsert user
        await NeonDB.execute(
            "INSERT INTO users (id) VALUES (%s) ON CONFLICT (id) DO NOTHING",
            (user_id,)
        )
        
        # Create chat
        chat = await NeonDB.execute_returning(
            """
            INSERT INTO chats (user_id, title)
            VALUES (%s, %s)
            RETURNING id, user_id, title, created_at, updated_at
            """,
            (user_id, None)
        )
        
        if not chat:
            raise HTTPException(status_code=500, detail="Failed to create chat")
        
        # Convert UUID to string
        chat_id_str = str(chat["id"])
        
        # Insert initial empty SQL version
        await NeonDB.execute(
            "INSERT INTO chat_sql_versions (chat_id, sql_text) VALUES (%s, %s)",
            (chat_id_str, "")
        )
        await update_chat_context_usage(chat_id_str, 0, 40000)
        
        # Convert UUID to string for response
        chat["id"] = chat_id_str
        
        return ChatResponse(**chat, latest_sql="")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create chat: {str(e)}")


@app.get("/api/chats", response_model=ChatListResponse)
async def list_chats(user_id: str = Depends(require_user_id)):
    """List all chats for the authenticated user."""
    try:
        chats = await NeonDB.fetch_all(
            """
            SELECT id, user_id, title, created_at, updated_at,
                   context_used_chars, context_cap_chars, context_usage_pct, context_updated_at
            FROM chats
            WHERE user_id = %s
            ORDER BY updated_at DESC
            """,
            (user_id,)
        )
        
        # Convert UUIDs to strings for JSON serialization
        for chat in chats:
            chat["id"] = str(chat["id"])
            chat["context_used_chars"] = chat.get("context_used_chars") or 0
            chat["context_cap_chars"] = chat.get("context_cap_chars") or 40000
            chat["context_usage_pct"] = chat.get("context_usage_pct") or 0
        
        return ChatListResponse(chats=[ChatResponse(**chat, latest_sql=None) for chat in chats])
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list chats: {str(e)}")


@app.get("/api/chats/{chat_id}", response_model=ChatResponse)
async def get_chat(chat_id: str, user_id: str = Depends(require_user_id)):
    """Get chat details including latest SQL."""
    try:
        # Get chat and verify ownership
        chat = await NeonDB.fetch_one(
            """
            SELECT id, user_id, title, created_at, updated_at,
                   context_used_chars, context_cap_chars, context_usage_pct, context_updated_at
            FROM chats
            WHERE id = %s AND user_id = %s
            """,
            (chat_id, user_id)
        )
        
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        
        # Get latest SQL
        latest_sql_row = await NeonDB.fetch_one(
            """
            SELECT sql_text
            FROM chat_sql_versions
            WHERE chat_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (chat_id,)
        )
        
        latest_sql = latest_sql_row["sql_text"] if latest_sql_row else ""
        
        # Convert UUID to string for JSON serialization
        chat["id"] = str(chat["id"])
        chat["context_used_chars"] = chat.get("context_used_chars") or 0
        chat["context_cap_chars"] = chat.get("context_cap_chars") or 40000
        chat["context_usage_pct"] = chat.get("context_usage_pct") or 0
        
        return ChatResponse(**chat, latest_sql=latest_sql)
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get chat: {str(e)}")


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str, user_id: str = Depends(require_user_id)):
    """Delete a chat and its SQL versions."""
    try:
        # Verify ownership
        chat = await NeonDB.fetch_one(
            "SELECT id FROM chats WHERE id = %s AND user_id = %s",
            (chat_id, user_id)
        )
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")

        # Delete related SQL versions first
        await NeonDB.execute(
            "DELETE FROM chat_sql_versions WHERE chat_id = %s",
            (chat_id,)
        )
        # Delete chat
        await NeonDB.execute(
            "DELETE FROM chats WHERE id = %s",
            (chat_id,)
        )
        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete chat: {str(e)}")


@app.post("/api/agent/stream")
async def agent_stream(request: AgentStreamRequest, user_id: str = Depends(require_user_id)):
    """
    Stream Claude responses with SSE.
    
    Events:
    - delta: Text chunk received
    - sql: SQL block detected/updated
    - done: Stream complete
    - error: Error occurred
    - tool: Tool call status
    - context: Context usage update
    - chat_rollover: New chat created due to context cap
    """
    return StreamingResponse(
        generate_sse_stream(request, user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/api/supabase/execute-sql", response_model=ExecuteSQLResponse)
async def execute_sql(request: ExecuteSQLRequest):
    """
    Execute SQL on a Supabase project via Management API.
    
    Requires user's Supabase Personal Access Token (PAT).
    """
    if not request.projectRef or not request.accessToken:
        raise HTTPException(
            status_code=400,
            detail="projectRef and accessToken are required"
        )
    
    if not request.query:
        raise HTTPException(
            status_code=400,
            detail="query is required"
        )
    
    try:
        # Call Supabase Management API
        url = f"https://api.supabase.com/v1/projects/{request.projectRef}/sql"
        headers = {
            "Authorization": f"Bearer {request.accessToken}",
            "Content-Type": "application/json"
        }
        payload = {"query": request.query}
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            data = response.json() if response.content else {}
            
            if response.status_code >= 400:
                return ExecuteSQLResponse(
                    success=False,
                    message=data.get("message", f"Error {response.status_code}: {response.reason_phrase}"),
                    data=data
                )
            
            return ExecuteSQLResponse(
                success=True,
                message="SQL executed successfully!",
                data=data
            )
    
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Request to Supabase timed out"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {str(e)}"
        )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "anthropic_configured": bool(os.getenv("ANTHROPIC_API_KEY"))
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
