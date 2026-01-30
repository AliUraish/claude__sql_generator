
import React from 'react';
import { SupabaseConfig } from '../types';

interface SettingsProps {
  config: SupabaseConfig;
  setConfig: (config: SupabaseConfig) => void;
}

const Settings: React.FC<SettingsProps> = ({ config, setConfig }) => {
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setConfig({ ...config, [name]: value });
  };

  return (
    <div className="p-6 bg-transparent border-b border-white/5 space-y-5">
      <div className="flex items-center space-x-3">
        <div className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-500 border border-emerald-500/20">
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
        </div>
        <span className="text-[11px] font-bold text-gray-400 uppercase tracking-widest">Connection Config</span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <label className="block text-[10px] text-gray-600 font-bold uppercase tracking-wider ml-1">Project ID</label>
          <input
            type="text"
            name="projectRef"
            value={config.projectRef}
            onChange={handleChange}
            placeholder="xyzabcde..."
            className="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-2.5 text-xs text-emerald-100 placeholder:text-gray-800 focus:outline-none focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/10 transition-all"
          />
        </div>
        <div className="space-y-1.5">
          <label className="block text-[10px] text-gray-600 font-bold uppercase tracking-wider ml-1">Access Token</label>
          <input
            type="password"
            name="accessToken"
            value={config.accessToken}
            onChange={handleChange}
            placeholder="••••••••••••"
            className="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-2.5 text-xs text-emerald-100 placeholder:text-gray-800 focus:outline-none focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/10 transition-all"
          />
        </div>
      </div>
    </div>
  );
};

export default Settings;
