"""FastAPI application for Claude DB Agent."""

import os
import json
import re
from typing import AsyncGenerator, List, Optional, Tuple
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from anthropic import Anthropic
import httpx

# AgentBasis SDK for AI agent observability
import agentbasis
from agentbasis import trace
from agentbasis.llms.anthropic import instrument as instrument_anthropic

from .api_models import (
    AgentStreamRequest, 
    ExecuteSQLRequest, 
    ExecuteSQLResponse,
    ChatResponse,
    ChatListResponse,
    MemoryQARequest,
    MemoryQAListResponse,
    MemoryQAItem
)
from .neon_db import NeonDB
from .clerk_auth import require_user_id

# Load environment variables
load_dotenv()

# System instruction for Claude (matching frontend UX)
SYSTEM_INSTRUCTION = """You are a world-class database architect and SQL expert specializing in Supabase (PostgreSQL).
Your task is to help users design and generate SQL schemas.

Tool Use Policy:
1. Prefer answering from existing context; do NOT call tools by default.
2. Ask a single clarifying question if requirements are unclear.
3. If confused, look for relevant memory snippets first; if not found, ask and proceed.

Strict Output Format:
1. Always provide a brief explanation of what you are building in plain text.
2. Always provide the actual SQL in a standard markdown code block: ```sql ... ```.
3. The UI will automatically hide the code block from the chat and show it in a dedicated editor.
4. DO NOT repeat the code outside the code block.

Database Rules:
1. Always output valid PostgreSQL SQL compatible with Supabase.
2. Adhere to PostgreSQL best practices: use snake_case, include RLS policies, foreign keys, and indexes.
3. Default schema is 'public'. If generating a fresh schema, include 'DROP TABLE IF EXISTS' for clean iterations.
4. If modifying an existing schema, output only the changed statements. Do not repeat unchanged SQL.
5. Replacement vs ALTER:
   - If the table being replaced exists in the current SQL script, prefer a full CREATE TABLE replacement (not ALTER).
   - If the table is not in the current SQL script, only use ALTER if the user confirms it already exists in Supabase.
   - If unclear, ask a short clarification question.
6. Use uppercase for SQL keywords.
7. Include concise comments starting with --."""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Startup
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("⚠️  Warning: ANTHROPIC_API_KEY not set")
    
    # Initialize AgentBasis SDK for observability
    agentbasis_initialized = False
    try:
        agentbasis_api_key = os.getenv("AGENTBASIS_API_KEY")
        agentbasis_agent_id = os.getenv("AGENTBASIS_AGENT_ID")
        if agentbasis_api_key and agentbasis_agent_id:
            agentbasis.init()
            instrument_anthropic()  # Auto-instrument all Anthropic calls
            agentbasis_initialized = True
            print("✓ AgentBasis SDK initialized with Anthropic instrumentation")
        else:
            print("⚠️  Warning: AGENTBASIS_API_KEY or AGENTBASIS_AGENT_ID not set, tracing disabled")
    except Exception as e:
        print(f"⚠️  AgentBasis initialization failed: {e}")
        agentbasis_initialized = False
    
    # Initialize Neon DB connection pool
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        NeonDB.initialize(database_url)
        print("✓ Neon DB connection pool initialized")
    else:
        print("⚠️  Warning: DATABASE_URL not set, chat persistence disabled")
    
    yield
    
    # Shutdown
    try:
        if agentbasis_initialized:
            agentbasis.shutdown()  # Ensure all traces are flushed
    except Exception as e:
        print(f"⚠️  AgentBasis shutdown failed: {e}")
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


@app.get("/health")
def health() -> dict:
    """Simple health check endpoint."""
    return {"status": "ok"}


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


def _split_sql_statements(sql_text: str) -> List[str]:
    """Split SQL into statements, respecting quotes, comments, and dollar-quoted blocks."""
    statements: List[str] = []
    buf: List[str] = []
    i = 0
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    dollar_tag: Optional[str] = None

    while i < len(sql_text):
        ch = sql_text[i]
        nxt = sql_text[i + 1] if i + 1 < len(sql_text) else ""

        if in_line_comment:
            buf.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                buf.append(nxt)
                i += 2
                in_block_comment = False
                continue
            i += 1
            continue

        if dollar_tag:
            if sql_text.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
            buf.append(ch)
            i += 1
            continue

        if not in_single and not in_double:
            if ch == "-" and nxt == "-":
                in_line_comment = True
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue
            if ch == "/" and nxt == "*":
                in_block_comment = True
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue
            if ch == "$":
                end = sql_text.find("$", i + 1)
                if end != -1:
                    tag = sql_text[i:end + 1]
                    if re.fullmatch(r"\$[A-Za-z_][A-Za-z0-9_]*\$", tag) or tag == "$$":
                        dollar_tag = tag
                        buf.append(tag)
                        i = end + 1
                        continue

        if ch == "'" and not in_double:
            if in_single and nxt == "'":
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue
            in_single = not in_single
            buf.append(ch)
            i += 1
            continue

        if ch == '"' and not in_single:
            if in_double and nxt == '"':
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue

        if ch == ";" and not in_single and not in_double:
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)

    return statements


def _normalize_object_name(name: str) -> str:
    cleaned = name.strip().strip('"')
    parts = [part.strip().strip('"') for part in cleaned.split(".")]
    return ".".join(part.lower() for part in parts if part)


def _get_object_key(statement: str) -> Optional[Tuple[str, str]]:
    patterns = [
        ("TABLE", r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_\".]+)"),
        ("VIEW", r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+([A-Za-z0-9_\".]+)"),
        ("FUNCTION", r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+([A-Za-z0-9_\".]+)"),
        ("TYPE", r"CREATE\s+TYPE\s+([A-Za-z0-9_\".]+)"),
        ("INDEX", r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_\".]+)"),
    ]
    for kind, pattern in patterns:
        match = re.search(pattern, statement, flags=re.IGNORECASE)
        if match:
            name = match.group(1)
            return kind, _normalize_object_name(name)
    return None


def _get_drop_table_key(statement: str) -> Optional[Tuple[str, str]]:
    match = re.search(
        r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?([A-Za-z0-9_\".]+)",
        statement,
        flags=re.IGNORECASE
    )
    if not match:
        return None
    name = match.group(1)
    return "TABLE", _normalize_object_name(name)


def _get_insert_table_key(statement: str) -> Optional[Tuple[str, str]]:
    match = re.search(
        r"INSERT\s+INTO\s+([A-Za-z0-9_\".]+)",
        statement,
        flags=re.IGNORECASE
    )
    if not match:
        return None
    name = match.group(1)
    return "TABLE", _normalize_object_name(name)


def _get_statement_table_refs(statement: str) -> set[Tuple[str, str]]:
    refs: set[Tuple[str, str]] = set()
    patterns = [
        r"INSERT\s+INTO\s+([A-Za-z0-9_\".]+)",
        r"UPDATE\s+([A-Za-z0-9_\".]+)",
        r"DELETE\s+FROM\s+([A-Za-z0-9_\".]+)",
        r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?([A-Za-z0-9_\".]+)",
        r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?[A-Za-z0-9_\".]+\s+ON\s+(?:ONLY\s+)?([A-Za-z0-9_\".]+)",
        r"CREATE\s+TRIGGER\s+[A-Za-z0-9_\".]+\s+.*\s+ON\s+([A-Za-z0-9_\".]+)",
        r"CREATE\s+POLICY\s+[A-Za-z0-9_\".]+\s+ON\s+([A-Za-z0-9_\".]+)",
        r"COMMENT\s+ON\s+TABLE\s+([A-Za-z0-9_\".]+)",
        r"GRANT\s+.*\s+ON\s+TABLE\s+([A-Za-z0-9_\".]+)",
        r"REVOKE\s+.*\s+ON\s+TABLE\s+([A-Za-z0-9_\".]+)",
        r"TRUNCATE\s+TABLE\s+(?:ONLY\s+)?([A-Za-z0-9_\".]+)",
        r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?([A-Za-z0-9_\".]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, statement, flags=re.IGNORECASE | re.DOTALL)
        if match:
            name = match.group(1)
            refs.add(("TABLE", _normalize_object_name(name)))
    return refs


def merge_sql_patch(existing_sql: str, patch_sql: str) -> str:
    """Merge patch SQL by replacing matching CREATE statements; append new ones."""
    existing = (existing_sql or "").strip()
    patch = (patch_sql or "").strip()
    if not existing:
        return patch
    if not patch:
        return existing

    existing_statements = _split_sql_statements(existing)
    patch_statements = _split_sql_statements(patch)

    existing_index: dict[tuple[str, str], int] = {}
    for idx, statement in enumerate(existing_statements):
        key = _get_object_key(statement)
        if key:
            existing_index[key] = idx

    additions: list[str] = []
    dropped_table_keys: set[Tuple[str, str]] = set()
    for statement in patch_statements:
        drop_key = _get_drop_table_key(statement)
        if drop_key:
            removed_any = False
            for idx, existing_stmt in enumerate(existing_statements):
                refs = _get_statement_table_refs(existing_stmt)
                if drop_key in refs:
                    existing_statements[idx] = ""
                    removed_any = True
            dropped_table_keys.add(drop_key)
            if not removed_any:
                additions.append(statement)
            continue
        key = _get_object_key(statement)
        if key and key in existing_index:
            existing_statements[existing_index[key]] = statement
        else:
            if key and key in dropped_table_keys:
                additions = [
                    stmt for stmt in additions
                    if _get_drop_table_key(stmt) != key
                ]
                dropped_table_keys.discard(key)
            refs = _get_statement_table_refs(statement)
            if refs.intersection(dropped_table_keys):
                continue
            additions.append(statement)

    merged_statements = [stmt for stmt in existing_statements if stmt.strip()]
    merged_statements.extend(stmt for stmt in additions if stmt.strip())

    if not merged_statements:
        return ""

    return ";\n\n".join(stmt.rstrip(";").strip() for stmt in merged_statements) + ";\n"


def should_use_memory(user_message: str) -> bool:
    """Detect if user is referencing previous context."""
    if not user_message:
        return False
    trigger_pattern = r"\b(previous|earlier|before|above|last time|as i said|as i mentioned|you said|we discussed|prior)\b"
    return re.search(trigger_pattern, user_message, re.IGNORECASE) is not None


def should_search_memory(user_message: str) -> bool:
    """Detect if memory lookup could resolve ambiguity or prior decisions."""
    if not user_message:
        return False
    trigger_pattern = (
        r"\b(previous|earlier|before|above|last time|as i said|as i mentioned|"
        r"you said|we discussed|prior|replace|rename|change|modify|update|alter|"
        r"same|similar|like before|as before)\b"
    )
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
    
    # Set AgentBasis context for per-user/session tracing
    try:
        agentbasis.set_user(user_id)
        agentbasis.set_session(request.chat_id)
    except Exception:
        pass  # Silently ignore if AgentBasis is not initialized
    
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
                "Output ONLY the minimal SQL patch needed to apply the change. "
                "Do NOT repeat the full schema."
            )
        
        # Check if Supermemory is available (optional)
        memory_context_str = ""  # String representation for context block
        memory_chunks_list = []  # List of chunks for later use
        
        if supermemory_api_key and (should_use_memory(request.message) or should_search_memory(request.message)):
            yield f"event: tool\ndata: {json.dumps({'name': 'get_summary_memory', 'status': 'start'})}\n\n"
            try:
                sm_client = SupermemoryClient(supermemory_api_key)
                memory_chunks_list = await sm_client.search_chat_memory(chat_id, user_id, request.message, limit=1, max_chars=3000)
                if memory_chunks_list:
                    memory_context_str = "\n\n".join(memory_chunks_list)
                    context_parts.append(f"\nMemory (from previous conversation):\n{memory_context_str}")
                qa_chunks = await sm_client.search_chat_qa(chat_id, user_id, query=request.message, limit=1, max_chars=2000)
                if qa_chunks:
                    context_parts.append(f"\nClarifications (from memory):\n{qa_chunks[0]}")
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
    finally:
        # Flush AgentBasis data (important for serverless environments like Vercel)
        try:
            agentbasis.flush()
        except Exception:
            pass  # Silently ignore if AgentBasis is not initialized


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


@app.post("/api/memory/qa")
async def save_memory_qa(request: MemoryQARequest, user_id: str = Depends(require_user_id)):
    """Save a clarification Q&A entry to Supermemory."""
    supermemory_api_key = os.getenv("SUPERMEMORY_API_KEY")
    if not supermemory_api_key:
        raise HTTPException(status_code=400, detail="Supermemory not configured")
    try:
        sm_client = SupermemoryClient(supermemory_api_key)
        success = await sm_client.create_chat_qa(
            chat_id=request.chat_id,
            user_id=user_id,
            question=request.question,
            answer=request.answer
        )
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save memory")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save memory: {str(e)}")


@app.get("/api/memory/qa", response_model=MemoryQAListResponse)
async def list_memory_qa(chat_id: str, user_id: str = Depends(require_user_id)):
    """List clarification Q&A entries for the chat."""
    supermemory_api_key = os.getenv("SUPERMEMORY_API_KEY")
    if not supermemory_api_key:
        return MemoryQAListResponse(items=[])
    try:
        sm_client = SupermemoryClient(supermemory_api_key)
        chunks = await sm_client.search_chat_qa(chat_id, user_id, query="Q:", limit=20, max_chars=6000)
        items = [MemoryQAItem(content=chunk) for chunk in chunks]
        return MemoryQAListResponse(items=items)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list memory: {str(e)}")


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
