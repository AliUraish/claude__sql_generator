"""Supermemory API client for per-chat context/summary storage."""

import os
from typing import List, Dict, Optional
import httpx


class SupermemoryClient:
    """Client for Supermemory API (v3 documents, v4 search)."""
    
    BASE_URL = "https://api.supermemory.ai"
    CONTEXT_CAP_CHARS = 40000  # ~10k tokens
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SUPERMEMORY_API_KEY")
        if not self.api_key:
            raise ValueError("SUPERMEMORY_API_KEY not set")
    
    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def update_chat_summary(
        self,
        chat_id: str,
        user_id: str,
        summary_content: str
    ) -> bool:
        """
        Update (or create) the rolling per-chat summary in Supermemory.
        Enforces cap by truncating content.
        """
        # Enforce cap
        if len(summary_content) > self.CONTEXT_CAP_CHARS:
            # Truncate from the beginning (keep most recent context)
            summary_content = "...[earlier context truncated]\n" + summary_content[-self.CONTEXT_CAP_CHARS:]
        
        custom_id = f"chat_summary_{chat_id}"
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/v3/documents",
                    headers=self._get_headers(),
                    json={
                        "content": summary_content,
                        "customId": custom_id,
                        "containerTag": user_id,
                        "metadata": {
                            "type": "chat_summary",
                            "chat_id": chat_id
                        }
                    }
                )
                
                if response.status_code >= 400:
                    print(f"⚠️  Supermemory update failed: {response.status_code} {response.text}")
                    return False
                
                return True
        
        except Exception as e:
            import traceback
            print(f"⚠️  Supermemory update error: {str(e)}")
            print(f"⚠️  Traceback: {traceback.format_exc()}")
            return False
    
    async def search_chat_memory(
        self,
        chat_id: str,
        user_id: str,
        query: str,
        limit: int = 1,
        max_chars: int = 3000,
        memory_type: str = "chat_summary"
    ) -> List[str]:
        """
        Search for relevant memory chunks for this chat.
        Returns list of memory/chunk strings, capped at max_chars total.
        """
        if not query or not query.strip():
            return []
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/v4/search",
                    headers=self._get_headers(),
                    json={
                        "q": query,
                        "containerTag": user_id,
                        "searchMode": "hybrid",
                        "limit": limit,
                        "filters": {
                            "AND": [
                                {"key": "type", "value": memory_type},
                                {"key": "chat_id", "value": chat_id}
                            ]
                        }
                    }
                )
                
                if response.status_code >= 400:
                    print(f"⚠️  Supermemory search failed: {response.status_code} {response.text}")
                    return []
                
                data = response.json()
                results = data.get("results", [])
                
                # Extract memory/chunk text and cap total length (top chunk only)
                chunks = []
                total_chars = 0
                
                for result in results:
                    # Handle both string and nested dict structures
                    text = None
                    if isinstance(result, dict):
                        # Try multiple possible keys for text content
                        text = result.get("memory") or result.get("chunk") or result.get("content")
                        
                        # If text is still a dict, try to extract content from it
                        if isinstance(text, dict):
                            text = text.get("content") or text.get("text")
                    elif isinstance(result, str):
                        text = result
                    
                    # Ensure text is actually a string
                    if text and isinstance(text, str):
                        if total_chars + len(text) > max_chars:
                            # Truncate to fit
                            remaining = max_chars - total_chars
                            if remaining > 100:  # Only add if meaningful
                                chunks.append(text[:remaining] + "...")
                            break
                        chunks.append(text)
                        total_chars += len(text)
                        break
                
                return chunks
        
        except Exception as e:
            import traceback
            print(f"⚠️  Supermemory search error: {str(e)}")
            print(f"⚠️  Traceback: {traceback.format_exc()}")
            return []

    async def create_chat_qa(
        self,
        chat_id: str,
        user_id: str,
        question: str,
        answer: str
    ) -> bool:
        """Store a clarification Q&A entry in Supermemory."""
        if not question or not answer:
            return False
        content = f"Q: {question.strip()}\nA: {answer.strip()}"
        custom_id = f"chat_qa_{chat_id}_{abs(hash(content))}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/v3/documents",
                    headers=self._get_headers(),
                    json={
                        "content": content,
                        "customId": custom_id,
                        "containerTag": user_id,
                        "metadata": {
                            "type": "chat_qa",
                            "chat_id": chat_id,
                            "question": question.strip(),
                            "answer": answer.strip()
                        }
                    }
                )
                if response.status_code >= 400:
                    print(f"⚠️  Supermemory QA save failed: {response.status_code} {response.text}")
                    return False
                return True
        except Exception as e:
            import traceback
            print(f"⚠️  Supermemory QA save error: {str(e)}")
            print(f"⚠️  Traceback: {traceback.format_exc()}")
            return False

    async def search_chat_qa(
        self,
        chat_id: str,
        user_id: str,
        query: str = "Q:",
        limit: int = 10,
        max_chars: int = 3000
    ) -> List[str]:
        """Search clarification Q&A entries for this chat."""
        return await self.search_chat_memory(
            chat_id=chat_id,
            user_id=user_id,
            query=query,
            limit=limit,
            max_chars=max_chars,
            memory_type="chat_qa"
        )
    
    def check_would_exceed_cap(self, current_summary: str, new_content: str) -> bool:
        """Check if adding new_content would exceed the cap."""
        combined_length = len(current_summary) + len(new_content)
        return combined_length > self.CONTEXT_CAP_CHARS
