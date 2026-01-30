#!/bin/bash

# Run the FastAPI server for Claude DB Agent

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

echo "🚀 Starting Claude DB Agent API server..."
echo "📡 Server will be available at http://localhost:8005"
echo "📚 API docs at http://localhost:8005/docs"
echo ""

# Run with uvicorn
uvicorn claude_db_agent.api:app --host 0.0.0.0 --port 8005 --reload
