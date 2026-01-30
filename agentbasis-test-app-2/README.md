<div align="center">
<img width="1200" height="475" alt="GHBanner" src="https://github.com/user-attachments/assets/0aa67016-6eaf-458a-adb2-6e31a0763ed6" />
</div>

# AgentBasis Test App 2 - Frontend

This is the frontend UI for the Claude-powered database schema generator. All AI logic runs in the backend.

## Prerequisites

- Node.js (v18 or higher)
- Backend API server running (see `../claude_backend/README.md`)

## Setup

1. Install dependencies:
   ```bash
   npm install
   ```

2. (Optional) Create a `.env.local` file to configure the backend URL:
   ```bash
   VITE_BACKEND_URL=http://localhost:8000
   ```
   
   If not set, it defaults to `http://localhost:8000`.

3. Run the development server:
   ```bash
   npm run dev
   ```

4. Open your browser to `http://localhost:3000`

## Usage

1. Enter your Supabase project reference ID and access token in the settings panel
2. Describe your database requirements in the chat
3. The backend (Claude) will generate a schema with SQL
4. Review the generated SQL in the right pane
5. Click "Deploy" to execute the SQL on your Supabase project

## Architecture

- **Frontend**: React + TypeScript (thin client)
- **Backend**: FastAPI + Claude API (all agent logic)
- **Database**: Supabase (PostgreSQL)

The frontend streams responses from the backend via Server-Sent Events (SSE) and displays them in real-time.
