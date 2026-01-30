"""Data models for database schema specifications."""

from typing import List, Optional
from pydantic import BaseModel, Field


class Column(BaseModel):
    """Database column specification."""
    name: str
    data_type: str
    nullable: bool = True
    primary_key: bool = False
    unique: bool = False
    default: Optional[str] = None
    references: Optional[str] = None  # Format: "table_name(column_name)"
    description: Optional[str] = None


class Index(BaseModel):
    """Database index specification."""
    name: str
    columns: List[str]
    unique: bool = False
    index_type: Optional[str] = None  # e.g., "btree", "gin", "gist"


class Table(BaseModel):
    """Database table specification."""
    name: str
    columns: List[Column]
    indexes: List[Index] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)  # Additional CHECK constraints, etc.
    description: Optional[str] = None


class DatabaseSchema(BaseModel):
    """Complete database schema specification."""
    tables: List[Table]
    extensions: List[str] = Field(default_factory=list)  # Postgres extensions like "uuid-ossp"
    sql: str  # The complete SQL DDL
    summary: str  # Human-readable description
    
    def get_table_names(self) -> List[str]:
        """Get list of all table names."""
        return [table.name for table in self.tables]
    
    def find_table(self, name: str) -> Optional[Table]:
        """Find a table by name."""
        for table in self.tables:
            if table.name == name:
                return table
        return None
