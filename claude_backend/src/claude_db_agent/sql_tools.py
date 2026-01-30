"""SQL versioning tools for chat context."""

import hashlib
from typing import List, Dict, Optional
from .neon_db import NeonDB


async def get_latest_sql(chat_id: str) -> str:
    """Get the latest SQL text for a chat."""
    result = await NeonDB.fetch_one(
        """
        SELECT sql_text
        FROM chat_sql_versions
        WHERE chat_id = %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (chat_id,)
    )
    return result["sql_text"] if result else ""


async def get_compact_sql_context(chat_id: str) -> str:
    """
    Get a token-efficient compact SQL context.
    Includes: hash, size, object inventory, tail snippet.
    """
    sql_text = await get_latest_sql(chat_id)
    
    if not sql_text or not sql_text.strip():
        return "No SQL defined yet."
    
    # Calculate hash and size
    sql_hash = hashlib.sha256(sql_text.encode()).hexdigest()[:16]
    char_count = len(sql_text)
    line_count = sql_text.count('\n') + 1
    
    # Extract object inventory (tables, views, functions)
    objects = []
    lines = sql_text.upper().split('\n')
    for line in lines:
        stripped = line.strip()
        if 'CREATE TABLE' in stripped:
            # Extract table name
            parts = stripped.split('CREATE TABLE')
            if len(parts) > 1:
                table_name = parts[1].strip().split()[0].strip('(').strip()
                objects.append(f"TABLE {table_name}")
        elif 'CREATE VIEW' in stripped:
            parts = stripped.split('CREATE VIEW')
            if len(parts) > 1:
                view_name = parts[1].strip().split()[0]
                objects.append(f"VIEW {view_name}")
        elif 'CREATE FUNCTION' in stripped or 'CREATE OR REPLACE FUNCTION' in stripped:
            if 'FUNCTION' in stripped:
                parts = stripped.split('FUNCTION')
                if len(parts) > 1:
                    func_name = parts[1].strip().split('(')[0]
                    objects.append(f"FUNCTION {func_name}")
    
    # Get last 10 lines as tail snippet
    tail_lines = sql_text.split('\n')[-10:]
    tail_snippet = '\n'.join(tail_lines)
    
    # Build compact context
    context_parts = [
        f"SQL Hash: {sql_hash}",
        f"Size: {char_count} chars, {line_count} lines",
    ]
    
    if objects:
        context_parts.append(f"Objects: {', '.join(objects[:20])}")  # Cap at 20
    
    context_parts.append(f"\nLast 10 lines:\n```sql\n{tail_snippet}\n```")
    
    return '\n'.join(context_parts)


async def get_full_sql(chat_id: str) -> str:
    """Get the full latest SQL (used only when model explicitly requests it)."""
    return await get_latest_sql(chat_id)


async def get_sql_versions(chat_id: str) -> List[Dict[str, any]]:
    """Get last 2 SQL versions (newest first)."""
    versions = await NeonDB.fetch_all(
        """
        SELECT id, sql_text, created_at
        FROM chat_sql_versions
        WHERE chat_id = %s
        ORDER BY created_at DESC
        LIMIT 2
        """,
        (chat_id,)
    )
    return versions


async def restore_sql(chat_id: str, version_index: int = 0) -> str:
    """
    Restore SQL from a previous version.
    version_index: 0 = most recent (previous), 1 = older
    Creates a new version row to track the restore action.
    """
    versions = await get_sql_versions(chat_id)
    
    if not versions:
        raise ValueError("No SQL versions found for this chat")
    
    if version_index < 0 or version_index >= len(versions):
        raise ValueError(f"Invalid version_index: {version_index}")
    
    # Get the SQL to restore
    sql_to_restore = versions[version_index]["sql_text"]
    
    # Insert as a new version (so restore is tracked)
    await NeonDB.execute(
        "INSERT INTO chat_sql_versions (chat_id, sql_text) VALUES (%s, %s)",
        (chat_id, sql_to_restore)
    )
    
    return sql_to_restore


async def save_new_sql_version(chat_id: str, sql_text: str) -> None:
    """Save a new SQL version for the chat."""
    await NeonDB.execute(
        "INSERT INTO chat_sql_versions (chat_id, sql_text) VALUES (%s, %s)",
        (chat_id, sql_text)
    )


async def update_chat_timestamp(chat_id: str) -> None:
    """Update the chat's updated_at timestamp."""
    await NeonDB.execute(
        "UPDATE chats SET updated_at = now() WHERE id = %s",
        (chat_id,)
    )


async def get_chat_context_usage(chat_id: str) -> Optional[Dict[str, int]]:
    """Get persisted context usage for a chat."""
    result = await NeonDB.fetch_one(
        """
        SELECT context_used_chars, context_cap_chars, context_usage_pct
        FROM chats
        WHERE id = %s
        """,
        (chat_id,)
    )
    if not result:
        return None
    return {
        "usedChars": int(result.get("context_used_chars") or 0),
        "capChars": int(result.get("context_cap_chars") or 40000),
        "usagePct": int(result.get("context_usage_pct") or 0),
    }


async def update_chat_context_usage(
    chat_id: str,
    used_chars: int,
    cap_chars: int = 40000
) -> None:
    """Persist context usage for a chat."""
    safe_used = max(0, int(used_chars))
    safe_cap = max(1, int(cap_chars))
    usage_pct = int(min((safe_used / safe_cap) * 100, 100))
    await NeonDB.execute(
        """
        UPDATE chats
        SET context_used_chars = %s,
            context_cap_chars = %s,
            context_usage_pct = %s,
            context_updated_at = now()
        WHERE id = %s
        """,
        (safe_used, safe_cap, usage_pct, chat_id)
    )
