
export interface Message {
  role: 'user' | 'model';
  text: string;
}

export interface SupabaseConfig {
  projectRef: string;
  accessToken: string;
}

export interface ExecutionResult {
  success: boolean;
  message: string;
  data?: any;
}

export interface Chat {
  id: string;
  user_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  latest_sql?: string;
  context_used_chars?: number;
  context_cap_chars?: number;
  context_usage_pct?: number;
  context_updated_at?: string | null;
}

export interface ToolStatus {
  name: string;
  status: 'start' | 'done' | 'error';
  timestamp: number;
}

export interface ContextUsage {
  chatId: string;
  usedChars: number;
  capChars: number;
  usagePct: number;
}
