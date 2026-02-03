import { Message, SupabaseConfig, ExecutionResult, Chat, ToolStatus, ContextUsage } from '../types';

const DEFAULT_BACKEND_URL = 'http://localhost:8005';
export const BACKEND_URL = (import.meta.env.VITE_BACKEND_URL || DEFAULT_BACKEND_URL).trim();

export interface SSEEvent {
  event: 'delta' | 'sql' | 'done' | 'error' | 'tool' | 'context' | 'chat_rollover';
  data: {
    textDelta?: string;
    fullText?: string;
    sql?: string;
    finalText?: string;
    finalSql?: string;
    message?: string;
    name?: string;
    status?: 'start' | 'done' | 'error';
    chatId?: string;
    usedChars?: number;
    capChars?: number;
    usagePct?: number;
    newChatId?: string;
  };
}

export class BackendService {
  private static authToken: string | null = null;

  static setAuthToken(token: string | null) {
    this.authToken = token;
    console.log('Auth token set:', token ? '✓' : '✗');
  }

  /**
   * Check if backend is accessible
   */
  static async checkBackendHealth(): Promise<boolean> {
    try {
      const response = await fetch(`${BACKEND_URL}/health`, {
        method: 'GET',
        headers: this.getHeaders(false), // No auth needed for health check
      });
      return response.ok;
    } catch {
      return false;
    }
  }

  private static getHeaders(includeAuth = true): HeadersInit {
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
    };
    if (includeAuth && this.authToken) {
      headers['Authorization'] = `Bearer ${this.authToken}`;
    }
    return headers;
  }

  /**
   * Create a new chat
   */
  static async createChat(): Promise<Chat> {
    try {
      console.log('➕ BackendService.createChat - Making request to:', `${BACKEND_URL}/api/chats/new`);
      console.log('➕ Auth token set:', this.authToken ? 'YES' : 'NO');
      
      const response = await fetch(`${BACKEND_URL}/api/chats/new`, {
        method: 'POST',
        headers: this.getHeaders(),
      });

      console.log('➕ Response status:', response.status, response.statusText);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: response.statusText }));
        const errorMessage = errorData.detail || errorData.message || `HTTP ${response.status}`;
        console.error('❌ createChat failed:', errorMessage);
        throw new Error(`Failed to create chat: ${errorMessage}`);
      }

      const chatData = await response.json();
      console.log('✅ createChat response:', chatData);
      return chatData;
    } catch (error: any) {
      console.error('❌ createChat error:', error);
      if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
        throw new Error('Cannot connect to backend. Is the server running?');
      }
      throw error;
    }
  }

  /**
   * List all chats for the user
   */
  static async listChats(): Promise<Chat[]> {
    console.log('🔍 BackendService.listChats - Making request to:', `${BACKEND_URL}/api/chats`);
    console.log('🔍 Auth token set:', this.authToken ? 'YES' : 'NO');
    
    const response = await fetch(`${BACKEND_URL}/api/chats`, {
      method: 'GET',
      headers: this.getHeaders(),
    });

    console.log('🔍 Response status:', response.status, response.statusText);

    if (!response.ok) {
      const errorText = await response.text();
      console.error('❌ listChats failed:', response.status, errorText);
      throw new Error(`Failed to list chats: ${response.status} - ${errorText}`);
    }

    const data = await response.json();
    console.log('✅ listChats response:', data);
    return data.chats;
  }

  /**
   * Get a specific chat with latest SQL
   */
  static async getChat(chatId: string): Promise<Chat> {
    try {
      const response = await fetch(`${BACKEND_URL}/api/chats/${chatId}`, {
        method: 'GET',
        headers: this.getHeaders(),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: response.statusText }));
        const errorMessage = errorData.detail || errorData.message || `HTTP ${response.status}`;
        
        if (response.status === 401) {
          throw new Error(`Authentication failed: ${errorMessage}. Please sign in again.`);
        }
        
        throw new Error(`Failed to get chat: ${errorMessage}`);
      }

      return await response.json();
    } catch (error: any) {
      if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
        throw new Error('Cannot connect to backend. Is the server running?');
      }
      throw error;
    }
  }

  /**
   * Delete a chat
   */
  static async deleteChat(chatId: string): Promise<void> {
    const response = await fetch(`${BACKEND_URL}/api/chats/${chatId}`, {
      method: 'DELETE',
      headers: this.getHeaders(),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Failed to delete chat: ${response.status} - ${errorText}`);
    }
  }

  /**
   * Stream agent responses from backend via SSE
   */
  static async *streamAgentResponse(
    message: string,
    chatId: string
  ): AsyncGenerator<SSEEvent, void, unknown> {
    const response = await fetch(`${BACKEND_URL}/api/agent/stream`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({
        message,
        chat_id: chatId,
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('No response body');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        let currentEvent: SSEEvent['event'] | null = null;

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.substring(7).trim() as SSEEvent['event'];
            continue;
          }

          if (line.startsWith('data: ')) {
            const dataStr = line.substring(6).trim();
            if (!dataStr) continue;

            try {
              const data = JSON.parse(dataStr);
              
              // Use explicit event type from event: line, or infer
              let eventType: SSEEvent['event'] = currentEvent || 'delta';
              if (!currentEvent) {
                // Fallback inference for backwards compat
                if (data.finalText !== undefined) {
                  eventType = 'done';
                } else if (data.message && !data.textDelta) {
                  eventType = 'error';
                } else if (data.sql !== undefined && data.textDelta === undefined) {
                  eventType = 'sql';
                } else if (data.name && data.status) {
                  eventType = 'tool';
                } else if (data.usedChars !== undefined) {
                  eventType = 'context';
                } else if (data.newChatId) {
                  eventType = 'chat_rollover';
                }
              }

              yield { event: eventType, data };
              currentEvent = null; // Reset after processing
            } catch (e) {
              console.error('Failed to parse SSE data:', dataStr, e);
            }
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  /**
   * Execute SQL on Supabase via backend
   */
  static async executeSql(
    config: SupabaseConfig,
    sql: string
  ): Promise<ExecutionResult> {
    if (!config.projectRef || !config.accessToken) {
      return {
        success: false,
        message: 'Supabase Project Ref or Access Token is missing.',
      };
    }

    try {
      const response = await fetch(`${BACKEND_URL}/api/supabase/execute-sql`, {
        method: 'POST',
        headers: this.getHeaders(false), // Don't require auth for this endpoint
        body: JSON.stringify({
          projectRef: config.projectRef,
          accessToken: config.accessToken,
          query: sql,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        return {
          success: false,
          message: data.detail || data.message || `Error ${response.status}`,
          data,
        };
      }

      return data;
    } catch (error: any) {
      return {
        success: false,
        message:
          error.message ||
          'An unexpected error occurred while communicating with the backend.',
      };
    }
  }
}
