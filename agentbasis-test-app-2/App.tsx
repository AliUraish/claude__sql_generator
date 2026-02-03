
import React, { useState, useRef, useEffect } from 'react';
import { useUser, useAuth, SignInButton, UserButton } from '@clerk/clerk-react';
import { BackendService, BACKEND_URL } from './services/backendService';
import { Message, SupabaseConfig, ExecutionResult, Chat, ToolStatus, ContextUsage } from './types';
import Settings from './components/Settings';
import SqlEditor from './components/SqlEditor';
import { format } from 'sql-formatter';

const App: React.FC = () => {
  const { isSignedIn, user } = useUser();
  const { getToken } = useAuth();

  const [messages, setMessages] = useState<Message[]>([
    { role: 'model', text: 'Define your data requirements. I will architect the schema and handle the deployment logic.' }
  ]);
  const [input, setInput] = useState('');
  const [sql, setSql] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [executionResult, setExecutionResult] = useState<ExecutionResult | null>(null);
  const [supabaseConfig, setSupabaseConfig] = useState<SupabaseConfig>({
    projectRef: '',
    accessToken: ''
  });

  // Chat state
  const [currentChatId, setCurrentChatId] = useState<string | null>(null);
  const [chats, setChats] = useState<Chat[]>([]);
  const [loadingChats, setLoadingChats] = useState(false);

  // Tool status
  const [activeTools, setActiveTools] = useState<ToolStatus[]>([]);

  // Context usage
  const [contextUsage, setContextUsage] = useState<ContextUsage | null>(null);
  const [showContextDetails, setShowContextDetails] = useState(false);

  // Chat history modal
  const [showChatHistory, setShowChatHistory] = useState(false);

  // Mobile SQL viewer
  const [showMobileSql, setShowMobileSql] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);

  const applyChatContextUsage = (chat: Chat | null) => {
    if (chat && chat.context_cap_chars !== undefined && chat.context_usage_pct !== undefined) {
      setContextUsage({
        chatId: chat.id,
        usedChars: chat.context_used_chars ?? 0,
        capChars: chat.context_cap_chars ?? 40000,
        usagePct: chat.context_usage_pct ?? 0
      });
    } else {
      setContextUsage(null);
    }
  };

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  // Initialize: Set auth token and create/load chats on sign-in
  useEffect(() => {
    if (isSignedIn) {
      (async () => {
        console.log('🔐 User signed in, initializing...', { isSignedIn, user: user?.id });
        
        // Check backend health first
        const isHealthy = await BackendService.checkBackendHealth();
        console.log('🏥 Backend health check:', isHealthy);
        if (!isHealthy) {
          setMessages(prev => [...prev, {
            role: 'model',
            text: `⚠️ Cannot connect to backend server. Please ensure the backend is running at ${BACKEND_URL}`
          }]);
          return;
        }

        // Get fresh token (Clerk handles refresh automatically)
        let token = await getToken({ template: 'default' }).catch(() => null);
        if (!token) {
          // Fallback: try without template
          token = await getToken().catch(() => null);
        }
        console.log('🎫 Got auth token:', token ? 'YES' : 'NO', token ? token.substring(0, 20) + '...' : 'NO TOKEN');
        if (token) {
          BackendService.setAuthToken(token);
          console.log('📞 Calling initializeChats...');
          await initializeChats();
        } else {
          console.error('❌ No auth token received');
          setMessages(prev => [...prev, {
            role: 'model',
            text: '⚠️ Could not get authentication token. Please sign in again.'
          }]);
        }
      })();
    } else {
      console.log('🚪 User signed out');
      BackendService.setAuthToken(null);
      setCurrentChatId(null);
      setChats([]);
    }
  }, [isSignedIn, getToken]);

  // Refresh token periodically and before API calls
  useEffect(() => {
    if (!isSignedIn) return;

    const refreshToken = async () => {
      try {
        let token = await getToken({ template: 'default' }).catch(() => null);
        if (!token) {
          token = await getToken().catch(() => null);
        }
        if (token) {
          BackendService.setAuthToken(token);
        }
      } catch (error) {
        console.error('Failed to refresh token:', error);
      }
    };

    // Refresh token every 5 minutes
    const interval = setInterval(refreshToken, 5 * 60 * 1000);
    
    return () => clearInterval(interval);
  }, [isSignedIn, getToken]);

  const initializeChats = async () => {
    try {
      console.log('🚀 initializeChats called');
      setLoadingChats(true);
      
      // Try to list existing chats
      console.log('📋 Fetching existing chats...');
      const existingChats = await BackendService.listChats();
      console.log('📋 Existing chats:', existingChats);
      
      if (existingChats.length === 0) {
        // No chats yet - wait for user to create one
        setChats([]);
        setCurrentChatId(null);
        setSql('');
        applyChatContextUsage(null);
      } else {
        // Use most recent chat
        console.log('✅ Using most recent chat:', existingChats[0].id);
        setChats(existingChats);
        setCurrentChatId(existingChats[0].id);
        // Load its SQL explicitly (list endpoint doesn't include latest_sql)
        try {
          console.log('📄 Loading chat SQL...');
          const chatDetails = await BackendService.getChat(existingChats[0].id);
          if (chatDetails.latest_sql) {
            setSql(formatSqlSafely(chatDetails.latest_sql));
          } else {
            setSql('');
          }
          applyChatContextUsage(chatDetails);
        } catch (error) {
          console.error('❌ Failed to load chat SQL:', error);
          setSql('');
          applyChatContextUsage(null);
        }
      }
    } catch (error: any) {
      console.error('❌ Failed to initialize chats:', error);
      setMessages(prev => [...prev, {
        role: 'model',
        text: `⚠️ ${error?.message || 'Failed to load chats. Please refresh the page.'}`
      }]);
    } finally {
      setLoadingChats(false);
      console.log('✅ initializeChats completed');
    }
  };

  const createNewChat = async () => {
    try {
      setLoadingChats(true);
      const newChat = await BackendService.createChat();
      setChats(prev => [newChat, ...prev]);
      setCurrentChatId(newChat.id);
      setSql('');
      applyChatContextUsage(newChat);
      setMessages([
        { role: 'model', text: 'Define your data requirements. I will architect the schema and handle the deployment logic.' }
      ]);
    } catch (error: any) {
      console.error('Failed to create chat:', error);
      setMessages(prev => [...prev, {
        role: 'model',
        text: `⚠️ ${error?.message || 'Failed to create chat. Please try again.'}`
      }]);
    } finally {
      setLoadingChats(false);
    }
  };

  const deleteChat = async (chatId: string) => {
    try {
      await BackendService.deleteChat(chatId);
      const remaining = chats.filter(chat => chat.id !== chatId);
      setChats(remaining);
      if (currentChatId === chatId) {
        if (remaining.length > 0) {
          await loadChat(remaining[0].id);
        } else {
          setCurrentChatId(null);
          setSql('');
          setMessages([
            { role: 'model', text: 'Define your data requirements. I will architect the schema and handle the deployment logic.' }
          ]);
          applyChatContextUsage(null);
        }
      }
    } catch (error: any) {
      console.error('Failed to delete chat:', error);
      setMessages(prev => [...prev, {
        role: 'model',
        text: `⚠️ ${error?.message || 'Failed to delete chat. Please try again.'}`
      }]);
    }
  };

  const loadChat = async (chatId: string) => {
    try {
      const chat = await BackendService.getChat(chatId);
      setCurrentChatId(chat.id);
      // Load SQL - always format it
      if (chat.latest_sql && chat.latest_sql.trim()) {
        setSql(formatSqlSafely(chat.latest_sql));
      } else {
        setSql('');
      }
      applyChatContextUsage(chat);
      // Clear messages for new chat
      setMessages([
        { role: 'model', text: 'Define your data requirements. I will architect the schema and handle the deployment logic.' }
      ]);
    } catch (error: any) {
      console.error('Failed to load chat:', error);
      setMessages(prev => [...prev, {
        role: 'model',
        text: `⚠️ Failed to load chat: ${error?.message || 'Unknown error'}`
      }]);
    }
  };

  const refreshChatList = async () => {
    try {
      const updatedChats = await BackendService.listChats();
      setChats(updatedChats);
    } catch (error) {
      console.error('Failed to refresh chats:', error);
    }
  };

  const formatSqlSafely = (rawSql: string): string => {
    try {
      return format(rawSql, {
        language: 'postgresql',
        keywordCase: 'upper',
        indentStyle: 'tabularLeft',
        linesBetweenQueries: 2,
      });
    } catch (e) {
      console.warn('SQL Formatting error:', e);
      return rawSql;
    }
  };

  const handleSendMessage = async () => {
    if (!input.trim() || isTyping) {
      console.log('Cannot send:', { input: input.trim(), isTyping });
      return;
    }

    // Ensure we have a chat before sending
    let chatId = currentChatId;
    if (!chatId) {
      setMessages(prev => [...prev, { 
        role: 'model', 
        text: '⚠️ Please create a new chat before sending a message.' 
      }]);
      return;
    }

    const userMessage = input;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', text: userMessage }]);
    setIsTyping(true);

    try {
      setMessages(prev => [...prev, { role: 'model', text: '' }]);
      
      // Stream from backend (no history sent)
      const stream = BackendService.streamAgentResponse(userMessage, chatId);
      
      let lastFullText = '';
      
      for await (const event of stream) {
        if (event.event === 'tool' && event.data.name && event.data.status) {
          // Tool status update
          const toolStatus: ToolStatus = {
            name: event.data.name,
            status: event.data.status,
            timestamp: Date.now()
          };
          setActiveTools(prev => {
            // Remove old status for this tool and add new
            const filtered = prev.filter(t => t.name !== event.data.name);
            if (event.data.status === 'start') {
              return [...filtered, toolStatus];
            } else {
              // For done/error, show briefly then fade
              setTimeout(() => {
                setActiveTools(current => current.filter(t => t.timestamp !== toolStatus.timestamp));
              }, 2000);
              return [...filtered, toolStatus];
            }
          });
        } else if (event.event === 'context' && event.data.chatId) {
          // Context usage update
          setContextUsage({
            chatId: event.data.chatId!,
            usedChars: event.data.usedChars!,
            capChars: event.data.capChars!,
            usagePct: event.data.usagePct!
          });
        } else if (event.event === 'chat_rollover' && event.data.newChatId) {
          // Context cap exceeded, switched to new chat
          const newChatId = event.data.newChatId;
          setCurrentChatId(newChatId);
          setSql(''); // New chat starts blank
          setContextUsage({
            chatId: newChatId,
            usedChars: 0,
            capChars: 40000,
            usagePct: 0
          });
          await refreshChatList();
          // Show notification
          setMessages(prev => [...prev, {
            role: 'model',
            text: '⚠️ Context limit reached. Continuing in a new chat session.'
          }]);
        } else if (event.event === 'delta' && event.data.fullText !== undefined) {
          const cleanedText = event.data.fullText.trim();
          if (cleanedText || lastFullText) {
            lastFullText = cleanedText;
            setMessages(prev => {
              const newMessages = [...prev];
              newMessages[newMessages.length - 1].text = cleanedText;
              return newMessages;
            });
          }
        } else if (event.event === 'sql' && event.data.sql) {
          setSql(event.data.sql);
        } else if (event.event === 'done') {
          if (event.data.finalText && event.data.finalText.trim()) {
            setMessages(prev => {
              const newMessages = [...prev];
              newMessages[newMessages.length - 1].text = event.data.finalText.trim();
              return newMessages;
            });
          }
          if (event.data.finalSql) {
            setSql(formatSqlSafely(event.data.finalSql));
          }
        } else if (event.event === 'error') {
          setMessages(prev => [...prev, { 
            role: 'model', 
            text: event.data.message || 'Error in architecture pipeline. Re-attempt advised.' 
          }]);
        }
      }
    } catch (error) {
      console.error('Stream error:', error);
      setMessages(prev => [...prev, { role: 'model', text: 'Error in architecture pipeline. Re-attempt advised.' }]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleExecute = async () => {
    if (!sql.trim()) return;
    
    setExecuting(true);
    setExecutionResult(null);
    
    try {
      const result = await BackendService.executeSql(supabaseConfig, sql);
      setExecutionResult(result);
      
      if (result.success) {
        setTimeout(() => setExecutionResult(null), 6000);
      }
    } catch (error) {
      setExecutionResult({ success: false, message: 'Critical deployment failure.' });
    } finally {
      setExecuting(false);
    }
  };

  // Show sign-in prompt if not authenticated
  if (!isSignedIn) {
    return (
      <div className="flex h-screen items-center justify-center bg-black text-gray-300">
        <div className="text-center space-y-6">
          <div className="w-20 h-20 mx-auto rounded-2xl bg-gradient-to-tr from-emerald-600 to-emerald-400 p-[1px] shadow-[0_0_30px_rgba(16,185,129,0.2)]">
            <div className="w-full h-full rounded-2xl bg-black flex items-center justify-center text-emerald-400">
              <svg className="w-10 h-10" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
              </svg>
            </div>
          </div>
          <h1 className="text-2xl font-bold text-white">AgentBasis Test App 2</h1>
          <p className="text-gray-400">Sign in to continue</p>
          <SignInButton mode="modal">
            <button className="px-6 py-3 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl font-semibold transition-all">
              Sign In
            </button>
          </SignInButton>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-transparent text-gray-300 relative z-10">
      {/* Sidebar: Interactions */}
      <div className="flex flex-col w-full md:w-[45%] h-full border-r border-white/5 bg-black/30 backdrop-blur-md">
        <div className="p-8 border-b border-white/5 flex items-center justify-between relative overflow-hidden group">
          <div className="absolute top-0 right-0 w-32 h-32 bg-emerald-500/5 blur-[60px] rounded-full -mr-10 -mt-10"></div>
          
          <div className="flex items-center space-x-6">
            <div className="relative">
              <div className="architect-glow"></div>
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-emerald-600 to-emerald-400 p-[1px] shadow-[0_0_30px_rgba(16,185,129,0.2)] transition-transform group-hover:scale-105 duration-500">
                <div className="w-full h-full rounded-2xl bg-black flex items-center justify-center text-emerald-400">
                  <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
                  </svg>
                </div>
              </div>
            </div>
            
            <div className="relative z-10">
              <h1 className="font-black text-lg uppercase tracking-[0.4em] text-white leading-tight">agentbasis test app 2</h1>
            </div>
          </div>

          <div className="relative z-10">
            <div className="flex items-center space-x-3">
              <button
                onClick={createNewChat}
                className="px-3 py-2 rounded-lg bg-emerald-600/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-600/30 transition-all text-xs uppercase tracking-wider"
                disabled={loadingChats}
                title="Create new chat"
              >
                New Chat
              </button>
              <button
                onClick={() => setShowMobileSql(true)}
                className="md:hidden px-3 py-2 rounded-lg bg-white/5 text-gray-300 border border-white/10 hover:bg-white/10 transition-all text-xs uppercase tracking-wider"
                title="View SQL output"
              >
                SQL
              </button>
              <UserButton afterSignOutUrl="/" />
            </div>
          </div>
        </div>

        <div className="bg-black/20">
          <Settings config={supabaseConfig} setConfig={setSupabaseConfig} />
        </div>

        <div className="flex-1 overflow-y-auto p-8 space-y-8 scroll-smooth" ref={scrollRef}>
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {/* Hide bubble if text is empty (e.g. while only SQL is being generated) */}
              {(m.text || m.role === 'user') && (
                <div 
                  className={`max-w-[90%] rounded-2xl px-6 py-4 transition-all duration-300 backdrop-blur-sm ${
                    m.role === 'user' 
                      ? 'bg-emerald-600/10 border border-emerald-500/20 text-emerald-100 rounded-br-none shadow-[0_4px_30px_rgba(16,185,129,0.08)]' 
                      : 'bg-black/40 text-gray-400 border border-white/5 rounded-bl-none hover:border-white/10'
                  }`}
                >
                  <div className="text-sm leading-relaxed tracking-wide whitespace-pre-wrap">
                    {m.text || (m.role === 'model' && isTyping && !m.text ? '...' : '')}
                  </div>
                </div>
              )}
            </div>
          ))}

          {/* Tool Status Display (inline, fading) */}
          {activeTools.length > 0 && (
            <div className="flex justify-start">
              <div className="max-w-[90%] rounded-2xl px-6 py-3 bg-black/60 border border-emerald-500/20 text-emerald-300 text-xs space-y-1">
                {activeTools.map((tool, idx) => (
                  <div key={idx} className="flex items-center space-x-2 animate-in fade-in duration-200">
                    <span>Tool: {tool.name}</span>
                    {tool.status === 'start' && <span className="animate-pulse">⏳</span>}
                    {tool.status === 'done' && <span>✓</span>}
                    {tool.status === 'error' && <span>✗</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="p-6 border-t border-white/5 bg-black/40 backdrop-blur-xl">
          {/* Context Usage Indicator (green line under input) */}
          <div className="mb-3">
            <div 
              className="flex items-center justify-between text-[10px] text-gray-500 mb-1 cursor-pointer hover:text-emerald-400 transition-colors"
              onClick={() => setShowContextDetails(!showContextDetails)}
              title="Click to see token details"
            >
              <span>Context Usage</span>
              <span>{contextUsage ? `${contextUsage.usagePct}%` : '0%'}</span>
            </div>
            <div 
              className="w-full h-1.5 bg-black/60 rounded-full overflow-hidden cursor-pointer hover:bg-black/70 transition-colors"
              onClick={() => setShowContextDetails(!showContextDetails)}
              title="Click to see token details"
            >
              <div 
                className="h-full bg-gradient-to-r from-emerald-500 to-emerald-400 transition-all duration-500 rounded-full shadow-[0_0_10px_rgba(16,185,129,0.5)]"
                style={{ width: `${contextUsage ? Math.min(contextUsage.usagePct, 100) : 0}%` }}
              />
            </div>
            
            {/* Token Details Tooltip */}
            {showContextDetails && contextUsage && (
              <div className="mt-2 p-3 bg-black/80 border border-emerald-500/20 rounded-xl text-xs text-gray-300 space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-gray-400">Characters:</span>
                  <span className="text-emerald-400 font-mono">
                    {contextUsage.usedChars.toLocaleString()} / {contextUsage.capChars.toLocaleString()}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-gray-400">Tokens (approx):</span>
                  <span className="text-emerald-400 font-mono">
                    {Math.round(contextUsage.usedChars / 4).toLocaleString()} / {Math.round(contextUsage.capChars / 4).toLocaleString()}
                  </span>
                </div>
                <div className="flex items-center justify-between pt-1 border-t border-white/5">
                  <span className="text-gray-400">Usage:</span>
                  <span className="text-emerald-400 font-semibold">{contextUsage.usagePct}%</span>
                </div>
              </div>
            )}
          </div>
          <div className="relative group flex items-center gap-2">
            {/* Chat History Button - Green Glowing Clock Icon */}
            <button
              onClick={() => setShowChatHistory(!showChatHistory)}
              className="flex-shrink-0 p-2.5 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20 hover:border-emerald-500/40 transition-all shadow-lg hover:shadow-emerald-500/20"
              style={{
                boxShadow: '0 0 15px rgba(16, 185, 129, 0.3), 0 0 30px rgba(16, 185, 129, 0.1)',
                animation: 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite'
              }}
              title="Chat History"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </button>
            <button
              onClick={createNewChat}
              className="flex-shrink-0 p-2.5 rounded-xl bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 hover:bg-emerald-500/20 hover:border-emerald-500/40 transition-all shadow-lg hover:shadow-emerald-500/20"
              title="New Chat"
              disabled={loadingChats}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
            </button>

            {/* Input Field */}
            <div className="flex-1 relative">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSendMessage();
                  }
                }}
                placeholder={loadingChats ? "Creating chat..." : "Design a modern blog schema with authors..."}
                className="w-full bg-black/40 border border-white/10 rounded-2xl px-6 py-5 pr-14 text-sm text-gray-200 placeholder:text-gray-700 focus:outline-none focus:border-emerald-500/30 focus:ring-1 focus:ring-emerald-500/10 transition-all group-hover:border-white/20 disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={loadingChats}
              />
              <button
                onClick={(e) => {
                  e.preventDefault();
                  handleSendMessage();
                }}
                disabled={isTyping || !input.trim() || loadingChats}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-3 rounded-xl bg-emerald-600/5 text-emerald-500 border border-emerald-500/10 disabled:opacity-20 disabled:cursor-not-allowed hover:bg-emerald-600 hover:text-white transition-all shadow-lg active:scale-95"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                </svg>
              </button>
            </div>
          </div>

          {/* Chat History Modal/Dropdown */}
          {showChatHistory && (
            <>
              {/* Backdrop */}
              <div 
                className="fixed inset-0 bg-black/50 z-40"
                onClick={() => setShowChatHistory(false)}
              />
              {/* Modal */}
              <div className="absolute bottom-full left-0 right-0 mb-2 bg-black/95 border border-emerald-500/20 rounded-2xl shadow-2xl backdrop-blur-xl z-50 max-h-96 overflow-hidden flex flex-col">
                <div className="p-4 border-b border-white/5 flex items-center justify-between">
                  <h3 className="text-sm font-bold text-emerald-400 uppercase tracking-wider flex items-center space-x-2">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span>Chat History</span>
                  </h3>
                  <button
                    onClick={() => setShowChatHistory(false)}
                    className="p-1 rounded-lg hover:bg-white/10 transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
                <div className="overflow-y-auto flex-1 p-2">
                  {chats.length === 0 ? (
                    <div className="text-center py-8 text-gray-500 text-sm">No chat history</div>
                  ) : (
                    <div className="space-y-1">
                      {chats.map((chat) => (
                        <div
                          key={chat.id}
                          className={`w-full text-left px-4 py-3 rounded-xl transition-all ${
                            chat.id === currentChatId
                              ? 'bg-emerald-500/20 border border-emerald-500/30 text-emerald-300'
                              : 'bg-black/40 border border-white/5 hover:bg-white/5 text-gray-300'
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex-1 min-w-0">
                              <button
                                onClick={() => {
                                  loadChat(chat.id);
                                  setShowChatHistory(false);
                                }}
                                className="text-sm font-medium truncate text-left w-full"
                              >
                                {chat.title || `Chat ${new Date(chat.created_at).toLocaleDateString()}`}
                              </button>
                              <div className="text-xs text-gray-500 mt-1">
                                {new Date(chat.updated_at).toLocaleString()}
                              </div>
                            </div>
                            <div className="flex items-center space-x-2">
                              {chat.id === currentChatId && (
                                <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
                              )}
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  deleteChat(chat.id);
                                }}
                                className="p-1 rounded-lg hover:bg-red-500/20 text-red-300"
                                title="Delete chat"
                              >
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                              </button>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Main Preview: SQL Viewer */}
      <div className="hidden md:flex flex-col flex-1 h-full relative z-10">
        <SqlEditor 
          sql={sql} 
          onExecute={handleExecute} 
          executing={executing}
          isGenerating={isTyping}
        />
        
        {/* Modern Status Overlay */}
        {executionResult && (
          <div className={`absolute bottom-8 left-1/2 -translate-x-1/2 px-8 py-5 rounded-3xl shadow-2xl border backdrop-blur-2xl transition-all transform animate-in fade-in slide-in-from-bottom-8 duration-500 flex items-center space-x-5 z-50 ${
            executionResult.success 
              ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-50 shadow-emerald-500/10' 
              : 'bg-red-950/40 border-red-500/40 text-red-50 shadow-red-500/10'
          }`}>
            <div className={`w-10 h-10 rounded-full flex items-center justify-center ${executionResult.success ? 'bg-emerald-500 text-black shadow-[0_0_20px_rgba(16,185,129,0.4)]' : 'bg-red-500 text-white shadow-[0_0_20px_rgba(239,68,68,0.4)]'}`}>
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                {executionResult.success ? (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                ) : (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M6 18L18 6M6 6l12 12" />
                )}
              </svg>
            </div>
            <div className="flex flex-col">
              <span className="text-xs font-black uppercase tracking-[0.2em]">{executionResult.success ? 'Deployment Complete' : 'Pipeline Error'}</span>
              <span className="text-[11px] opacity-60 mt-0.5 max-w-[200px] truncate">{executionResult.message}</span>
            </div>
            <button 
              onClick={() => setExecutionResult(null)}
              className="ml-6 p-2 rounded-xl hover:bg-white/10 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        )}

      </div>

      {showMobileSql && (
        <div className="fixed inset-0 z-50 flex items-end md:hidden">
          <div
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            onClick={() => setShowMobileSql(false)}
          />
          <div className="relative w-full h-[85vh] rounded-t-3xl border border-white/10 bg-black/80 shadow-2xl overflow-hidden">
            <button
              onClick={() => setShowMobileSql(false)}
              className="absolute top-3 right-3 z-20 p-2 rounded-xl bg-white/5 text-gray-300 border border-white/10 hover:bg-white/10 transition-all"
              title="Close SQL viewer"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
            <SqlEditor
              sql={sql}
              onExecute={handleExecute}
              executing={executing}
              isGenerating={isTyping}
              className="border-l-0 border-t border-white/10 rounded-t-3xl"
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default App;
