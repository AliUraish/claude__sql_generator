"""Neon Postgres database access layer."""

import os
import asyncio
from typing import Any, Dict, List, Optional
from contextlib import contextmanager
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor


class NeonDB:
    """Neon Postgres connection pool and query helpers."""
    
    _pool: Optional[pool.ThreadedConnectionPool] = None
    
    @classmethod
    def initialize(cls, database_url: str, min_conn: int = 1, max_conn: int = 10):
        """Initialize connection pool."""
        if cls._pool is None:
            cls._pool = pool.ThreadedConnectionPool(
                min_conn,
                max_conn,
                database_url
            )
    
    @classmethod
    @contextmanager
    def get_connection(cls):
        """Get a connection from the pool."""
        if cls._pool is None:
            raise RuntimeError("Database pool not initialized. Call NeonDB.initialize() first.")
        
        conn = cls._pool.getconn()
        try:
            yield conn
        finally:
            cls._pool.putconn(conn)
    
    @classmethod
    async def fetch_one(cls, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """Execute query and return one row as dict."""
        def _execute():
            with cls.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, params)
                    result = cur.fetchone()
                    return dict(result) if result else None
        
        return await asyncio.to_thread(_execute)
    
    @classmethod
    async def fetch_all(cls, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Execute query and return all rows as list of dicts."""
        def _execute():
            with cls.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, params)
                    results = cur.fetchall()
                    return [dict(row) for row in results]
        
        return await asyncio.to_thread(_execute)
    
    @classmethod
    async def execute(cls, query: str, params: tuple = (), commit: bool = True) -> int:
        """Execute query and return rowcount."""
        def _execute():
            with cls.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    rowcount = cur.rowcount
                    if commit:
                        conn.commit()
                    return rowcount
        
        return await asyncio.to_thread(_execute)
    
    @classmethod
    async def execute_returning(cls, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """Execute query with RETURNING clause and return the row."""
        def _execute():
            with cls.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, params)
                    result = cur.fetchone()
                    conn.commit()
                    return dict(result) if result else None
        
        return await asyncio.to_thread(_execute)
    
    @classmethod
    def close_pool(cls):
        """Close all connections in the pool."""
        if cls._pool:
            cls._pool.closeall()
            cls._pool = None
