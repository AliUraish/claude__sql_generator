# Claude Test Agent - Full Stack Application

A full-stack application for AI-powered database schema generation using Claude and Supabase.

## Architecture

- **Backend** (`claude_backend/`): Python FastAPI server with Claude integration
- **Frontend** (`agentbasis-test-app-2/`): React + TypeScript UI

All AI logic runs in the backend using Claude (Anthropic). The frontend is a thin client that streams responses via Server-Sent Events (SSE).

## Quick Start

### 1. Backend Setup

```bash
cd claude_backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Start the API server
./run_api.sh
```

The backend will run at `http://localhost:8005`

### 2. Frontend Setup

```bash
cd agentbasis-test-app-2

# Install dependencies
npm install

# (Optional) Configure backend URL
cp .env.example .env
# Edit if backend is not at http://localhost:8005

# Start the development server
npm run dev
```

The frontend will run at `http://localhost:3000`

## Usage

1. Open `http://localhost:3000` in your browser
2. Enter your Supabase project reference ID and Personal Access Token in the settings
3. Describe your database requirements in the chat
4. Claude will generate a schema with SQL in real-time
5. Review the SQL and click "Deploy" to execute it on your Supabase project

## Getting API Keys

### Anthropic API Key (Required)
1. Sign up at https://console.anthropic.com/
2. Create an API key
3. Add it to `claude_backend/.env` as `ANTHROPIC_API_KEY`

### Supabase Personal Access Token (Required for SQL Execution)
1. Go to https://supabase.com/dashboard/account/tokens
2. Create a new token
3. Enter it in the frontend UI when deploying SQL

## Project Structure

```
.
├── claude_backend/              # Python FastAPI backend
│   ├── src/claude_db_agent/
│   │   ├── api.py              # FastAPI application
│   │   ├── api_models.py       # Request/response models
│   │   ├── claude_client.py    # Claude API client
│   │   ├── supabase_api.py     # Supabase Management API client
│   │   └── cli.py              # Legacy CLI interface
│   ├── requirements.txt
│   ├── .env                    # Backend config (gitignored)
│   └── run_api.sh              # Start script
│
└── agentbasis-test-app-2/      # React frontend
    ├── services/
    │   └── backendService.ts   # Backend API client
    ├── components/
    │   ├── Settings.tsx        # Supabase config UI
    │   └── SqlEditor.tsx       # SQL display/execution
    ├── App.tsx                 # Main application
    ├── package.json
    └── .env.local              # Frontend config (gitignored)
```

## Features

- **Real-time streaming**: Claude responses stream token-by-token to the UI
- **SQL extraction**: Backend automatically extracts and formats SQL from Claude's response
- **Supabase integration**: Direct SQL execution on Supabase projects via Management API
- **Secure**: API keys stay server-side, user tokens never persisted
- **Type-safe**: Full TypeScript on frontend, Pydantic on backend

## API Documentation

Once the backend is running, visit:
- Interactive API docs: http://localhost:8005/docs
- Alternative docs: http://localhost:8005/redoc

## Security Notes

⚠️ **IMPORTANT**: Never commit `.env` files with real credentials to version control.
- Both backend and frontend `.env` files are in `.gitignore`
- Always use `.env.example` files as templates
- Keep your API keys and tokens secure

## Troubleshooting

### Backend won't start
- Ensure Python 3.9+ is installed
- Check that `ANTHROPIC_API_KEY` is set in `.env`
- Verify all dependencies are installed: `pip install -r requirements.txt`

### Frontend can't connect to backend
- Ensure backend is running at `http://localhost:8005`
- Check `VITE_BACKEND_URL` in frontend `.env`
- Check browser console for CORS errors

### SQL execution fails
- Verify your Supabase project reference ID is correct
- Ensure your Personal Access Token has the required permissions
- Check the SQL syntax is valid PostgreSQL

## Development

### Backend
```bash
cd claude_backend
source .venv/bin/activate
uvicorn claude_db_agent.api:app --reload
```

### Frontend
```bash
cd agentbasis-test-app-2
npm run dev
```

## License

MIT
