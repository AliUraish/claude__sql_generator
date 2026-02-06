"""Anthropic tool definitions for Claude DB Agent.

This module defines the tools that Claude can use during conversations
to programmatically access SQL context, memory, and versioning features.
"""

from typing import List, Dict, Any, Optional

# Tool definitions following Anthropic's tool calling format
AGENT_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "get_sql_context",
        "description": """Retrieves the current SQL schema context for this chat session.
Use this tool when:
- The user asks about the current database schema
- You need to understand what tables/views/functions already exist
- The user wants to modify, extend, or reference existing SQL
- You're unsure what schema objects have been defined

Returns a compact summary including: schema hash, size metrics, object inventory (tables, views, functions), and the last 10 lines of SQL.""",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_full_sql",
        "description": """Retrieves the complete, full SQL schema text for this chat session.
Use this tool when:
- You need the exact SQL code, not just a summary
- The user asks to see the complete schema
- You need to make precise edits that require seeing all code
- The compact context is insufficient for the task

Note: This returns the entire SQL which may be large. Prefer get_sql_context for most cases.""",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "search_memory",
        "description": """Searches the conversation memory for relevant prior context.
Use this tool when:
- The user references something discussed earlier ("as I mentioned", "like before", etc.)
- You need to recall decisions or clarifications made in this chat
- The user asks about previous requirements or changes
- You're uncertain about prior context that may affect the current request

Returns relevant memory snippets from the conversation history.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to find relevant memory. Be specific about what you're looking for."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "search_clarifications",
        "description": """Searches saved Q&A clarifications for this chat.
Use this tool when:
- Looking for specific answers the user provided to your questions
- Need to recall important decisions or preferences stated by the user
- Want to avoid asking the same clarifying question twice

Returns Q&A pairs that were explicitly saved as clarifications.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to find relevant clarifications."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_sql_versions",
        "description": """Retrieves the last 2 SQL versions for comparison or restoration.
Use this tool when:
- The user wants to undo recent changes
- You need to compare current SQL with the previous version
- The user asks about what changed recently
- Considering whether to restore a previous version

Returns the 2 most recent SQL versions with timestamps.""",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "restore_sql_version",
        "description": """Restores SQL to a previous version.
Use this tool when:
- The user explicitly asks to undo or revert changes
- The user wants to go back to a previous version
- Recent changes need to be discarded

Creates a new version entry for the restored SQL (so restoration is tracked).""",
        "input_schema": {
            "type": "object",
            "properties": {
                "version_index": {
                    "type": "integer",
                    "description": "Which version to restore: 0 = most recent previous version, 1 = older version",
                    "enum": [0, 1]
                }
            },
            "required": ["version_index"]
        }
    }
]


def get_tool_definitions() -> List[Dict[str, Any]]:
    """Returns the list of tool definitions for the Anthropic API."""
    return AGENT_TOOLS


def get_tool_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Get a specific tool definition by name."""
    for tool in AGENT_TOOLS:
        if tool["name"] == name:
            return tool
    return None
