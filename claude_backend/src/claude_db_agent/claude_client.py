"""Claude API client for schema generation."""

import json
import os
from typing import Optional
from anthropic import Anthropic
from .schema_model import DatabaseSchema

# Initialize AgentBasis SDK (optional, for monitoring)
try:
    import agentbasis
    agentbasis.init()
    from agentbasis.llms.anthropic import instrument
    instrument()
except ImportError:
    # AgentBasis not installed, continue without instrumentation
    pass

SCHEMA_GENERATION_PROMPT = """You are a database schema expert. Analyze the following application description and generate a complete, production-ready Postgres database schema.

Application Description:
{app_description}

Your task:
1. Identify all entities/tables needed
2. Define appropriate columns with correct data types
3. Set up primary keys, foreign keys, and constraints
4. Add indexes for performance
5. Include any necessary Postgres extensions
6. Generate the complete SQL DDL

Return your response as a JSON object with this EXACT structure:
{{
  "tables": [
    {{
      "name": "table_name",
      "description": "Brief description of this table",
      "columns": [
        {{
          "name": "column_name",
          "data_type": "data_type (e.g., 'UUID', 'TEXT', 'INTEGER', 'TIMESTAMP WITH TIME ZONE', 'BOOLEAN')",
          "nullable": true/false,
          "primary_key": true/false,
          "unique": true/false,
          "default": "default_value (optional)",
          "references": "table_name(column_name) (optional, for foreign keys)",
          "description": "Column purpose (optional)"
        }}
      ],
      "indexes": [
        {{
          "name": "idx_name",
          "columns": ["column1", "column2"],
          "unique": true/false,
          "index_type": "btree/gin/gist (optional)"
        }}
      ],
      "constraints": ["CHECK (condition)", "UNIQUE(col1, col2)"]
    }}
  ],
  "extensions": ["uuid-ossp", "pgcrypto"],
  "sql": "-- Complete Postgres SQL DDL here\\nCREATE EXTENSION IF NOT EXISTS ...",
  "summary": "A brief overview of the schema and key design decisions"
}}

Guidelines:
- Use UUID for primary keys where appropriate
- Always include created_at and updated_at timestamps for data tables
- Use proper foreign key constraints with ON DELETE CASCADE/SET NULL as appropriate
- Add indexes on foreign keys and frequently queried columns
- Use TEXT instead of VARCHAR unless there's a specific length requirement
- Include proper constraints (NOT NULL, CHECK, UNIQUE)
- Consider adding indexes for common query patterns
- Use TIMESTAMP WITH TIME ZONE for all timestamp columns
- The SQL should be complete and ready to execute
- Include CREATE TABLE IF NOT EXISTS statements
- Order tables to respect foreign key dependencies

Return ONLY the JSON object, no other text."""


class ClaudeSchemaGenerator:
    """Client for generating database schemas using Claude."""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Claude client.
        
        Args:
            api_key: Anthropic API key. If not provided, reads from ANTHROPIC_API_KEY env var.
        """
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not found. Please set it in your .env file or environment."
            )
        
        # Configure client with explicit timeouts to prevent indefinite hangs
        import httpx
        self.client = Anthropic(
            api_key=self.api_key,
            timeout=httpx.Timeout(60.0, connect=10.0),  # 60s total, 10s connect
            max_retries=2
        )
    
    def generate_schema(self, app_description: str, model: str = "claude-sonnet-4-20250514") -> DatabaseSchema:
        """Generate a database schema from an app description.
        
        Args:
            app_description: Free-text description of the application
            model: Claude model to use
            
        Returns:
            DatabaseSchema object containing the generated schema
            
        Raises:
            ValueError: If the response cannot be parsed
            Exception: If the API call fails
        """
        prompt = SCHEMA_GENERATION_PROMPT.format(app_description=app_description)
        
        print("🤖 Asking Claude to analyze your app and design the database schema...")
        print("⏳ This may take 20-40 seconds for complex schemas...")
        
        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=8192,  # Balanced for speed and completeness
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            
            print(f"✓ Schema generated successfully!")
            
            # Extract the text content
            content = response.content[0].text
            
            # Try to parse as JSON
            try:
                # Sometimes Claude wraps JSON in markdown code blocks
                if content.strip().startswith("```"):
                    # Extract JSON from code block
                    lines = content.strip().split("\n")
                    json_lines = []
                    in_code_block = False
                    for line in lines:
                        if line.strip().startswith("```"):
                            in_code_block = not in_code_block
                            continue
                        if in_code_block or not line.strip().startswith("```"):
                            json_lines.append(line)
                    content = "\n".join(json_lines)
                
                schema_dict = json.loads(content)
                schema = DatabaseSchema(**schema_dict)
                return schema
                
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse Claude's response as JSON: {e}\n\nResponse:\n{content}")
            except Exception as e:
                raise ValueError(f"Failed to validate schema structure: {e}\n\nParsed data:\n{schema_dict}")
                
        except Exception as e:
            raise Exception(f"Claude API call failed: {e}")
    
    def save_schema_artifacts(self, schema: DatabaseSchema, output_dir: str = "./out") -> dict:
        """Save schema artifacts to files.
        
        Args:
            schema: The database schema to save
            output_dir: Directory to save files to
            
        Returns:
            Dictionary with paths to saved files
        """
        os.makedirs(output_dir, exist_ok=True)
        
        # Save JSON specification
        json_path = os.path.join(output_dir, "schema.json")
        with open(json_path, "w") as f:
            f.write(schema.model_dump_json(indent=2))
        
        # Save SQL
        sql_path = os.path.join(output_dir, "schema.sql")
        with open(sql_path, "w") as f:
            f.write(schema.sql)
        
        # Generate and save human-readable summary
        summary_md = self._generate_summary_markdown(schema)
        summary_path = os.path.join(output_dir, "summary.md")
        with open(summary_path, "w") as f:
            f.write(summary_md)
        
        return {
            "json": json_path,
            "sql": sql_path,
            "summary": summary_path
        }
    
    def _generate_summary_markdown(self, schema: DatabaseSchema) -> str:
        """Generate a human-readable markdown summary of the schema."""
        lines = ["# Database Schema Summary\n"]
        lines.append(f"{schema.summary}\n")
        lines.append(f"## Tables ({len(schema.tables)})\n")
        
        for table in schema.tables:
            lines.append(f"### {table.name}\n")
            if table.description:
                lines.append(f"*{table.description}*\n")
            
            lines.append("**Columns:**\n")
            for col in table.columns:
                flags = []
                if col.primary_key:
                    flags.append("PK")
                if not col.nullable:
                    flags.append("NOT NULL")
                if col.unique:
                    flags.append("UNIQUE")
                if col.references:
                    flags.append(f"FK → {col.references}")
                
                flag_str = f" `[{', '.join(flags)}]`" if flags else ""
                default_str = f" (default: `{col.default}`)" if col.default else ""
                
                lines.append(f"- **{col.name}**: `{col.data_type}`{flag_str}{default_str}")
                if col.description:
                    lines.append(f"  - {col.description}")
            
            if table.indexes:
                lines.append("\n**Indexes:**\n")
                for idx in table.indexes:
                    idx_type = f" ({idx.index_type})" if idx.index_type else ""
                    unique = " UNIQUE" if idx.unique else ""
                    lines.append(f"- `{idx.name}`: {', '.join(idx.columns)}{unique}{idx_type}")
            
            if table.constraints:
                lines.append("\n**Constraints:**\n")
                for constraint in table.constraints:
                    lines.append(f"- {constraint}")
            
            lines.append("")
        
        if schema.extensions:
            lines.append(f"## Postgres Extensions\n")
            for ext in schema.extensions:
                lines.append(f"- {ext}")
            lines.append("")
        
        return "\n".join(lines)
