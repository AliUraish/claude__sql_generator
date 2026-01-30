
import React, { useState } from 'react';

interface SqlEditorProps {
  sql: string;
  onExecute: () => void;
  executing: boolean;
  isGenerating: boolean;
}

const SqlEditor: React.FC<SqlEditorProps> = ({ sql, onExecute, executing, isGenerating }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (!sql) return;
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy text: ', err);
    }
  };

  return (
    <div className={`flex flex-col h-full bg-black/20 border-l border-white/5 transition-all duration-700 backdrop-blur-[2px] ${isGenerating ? 'ring-1 ring-emerald-500/30' : ''}`}>
      <div className="p-4 border-b border-white/5 flex justify-between items-center glass-panel z-10">
        <h2 className="text-xs font-bold text-gray-500 uppercase tracking-[0.2em] flex items-center">
          <span className={`w-2 h-2 rounded-full mr-3 ${isGenerating ? 'bg-emerald-500 animate-pulse' : 'bg-gray-700'}`}></span>
          Schema Output
        </h2>
        <div className="flex items-center space-x-3">
          <button
            onClick={handleCopy}
            disabled={!sql.trim()}
            className={`px-4 py-2 rounded-full text-[10px] font-bold uppercase tracking-wider transition-all flex items-center border ${
              copied 
                ? 'bg-emerald-500/20 border-emerald-500 text-emerald-400' 
                : 'bg-white/5 border-white/10 hover:bg-white/10 text-gray-400 disabled:opacity-30 disabled:cursor-not-allowed'
            }`}
            title="Copy to clipboard"
          >
            {copied ? (
              <>
                <svg className="w-3 h-3 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                </svg>
                Copied
              </>
            ) : (
              <>
                <svg className="w-3 h-3 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
                </svg>
                Copy SQL
              </>
            )}
          </button>
          
          <button
            onClick={onExecute}
            disabled={executing || !sql.trim() || isGenerating}
            className={`px-5 py-2 rounded-full text-xs font-bold uppercase tracking-wider transition-all flex items-center border ${
              executing 
                ? 'bg-emerald-950/50 border-emerald-500/30 text-emerald-400 cursor-not-allowed' 
                : 'bg-emerald-600 border-emerald-500 hover:bg-emerald-500 text-white shadow-[0_0_20px_rgba(16,185,129,0.2)] disabled:opacity-30 disabled:grayscale'
            }`}
          >
            {executing ? (
              <>
                <svg className="animate-spin -ml-1 mr-2 h-3 w-3 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Deploying
              </>
            ) : (
              <>
                <svg className="w-3 h-3 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                Deploy
              </>
            )}
          </button>
        </div>
      </div>
      <div className="flex-1 relative overflow-hidden">
        {isGenerating && <div className="scan-line"></div>}
        {isGenerating && <div className="absolute inset-0 generating-overlay z-0 animate-pulse"></div>}
        
        <div className="absolute inset-0 p-8 overflow-auto mono text-sm selection:bg-emerald-500/30">
          {sql ? (
            <pre className="text-emerald-400 leading-relaxed whitespace-pre-wrap">
              {sql.split('\n').map((line, i) => (
                <div key={i} className="flex group">
                  <span className="inline-block w-8 text-gray-500/40 select-none mr-4 text-right tabular-nums">{i + 1}</span>
                  <span className={`${line.trim().startsWith('--') ? 'text-gray-600 italic' : ''}`}>
                    {line}
                  </span>
                </div>
              ))}
            </pre>
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-gray-700 space-y-4 opacity-40">
              <svg className="w-12 h-12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
              </svg>
              <p className="text-xs uppercase tracking-[0.3em]">Awaiting Architect Input</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SqlEditor;
