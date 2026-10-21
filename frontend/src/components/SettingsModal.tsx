import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { KeyRound, Shield, Save, X, CheckCircle2, AlertTriangle } from 'lucide-react';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialAuthError?: boolean;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  initialAuthError = false,
}) => {
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('signal_desk_api_key') || '');
  const [savedSuccess, setSavedSuccess] = useState(false);
  const [authError, setAuthError] = useState(initialAuthError);

  if (!isOpen) return null;

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    const cleanKey = apiKey.trim();
    if (cleanKey) {
      localStorage.setItem('signal_desk_api_key', cleanKey);
      axios.defaults.headers.common['X-API-Key'] = cleanKey;
    } else {
      localStorage.removeItem('signal_desk_api_key');
      delete axios.defaults.headers.common['X-API-Key'];
    }
    setSavedSuccess(true);
    setAuthError(false);
    setTimeout(() => {
      onClose();
    }, 800);
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-modal-title"
    >
      <div className="bg-gray-900 border border-gray-800 rounded-xl max-w-md w-full p-6 space-y-5 shadow-2xl relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-400 hover:text-white transition-colors"
          aria-label="Close settings"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-3 border-b border-gray-800 pb-3">
          <div className="p-2 rounded-lg bg-blue-950 text-blue-400 border border-blue-800">
            <KeyRound className="w-5 h-5" />
          </div>
          <div>
            <h2 id="settings-modal-title" className="text-lg font-bold text-white">
              Workspace Settings &amp; Authentication
            </h2>
            <p className="text-xs text-gray-400">Configure client API keys and operational parameters.</p>
          </div>
        </div>

        {authError && (
          <div className="bg-red-950/70 border border-red-800 p-3 rounded-lg flex items-start gap-2.5 text-xs text-red-200">
            <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            <div>
              <strong>Authentication Required (HTTP 403)</strong>
              <p className="mt-0.5 text-red-300">This production backend requires a valid API key. Enter your key below to unlock endpoints.</p>
            </div>
          </div>
        )}

        {savedSuccess && (
          <div className="bg-emerald-950/70 border border-emerald-800 p-3 rounded-lg flex items-center gap-2 text-xs text-emerald-300">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            API Key saved successfully! Reloading workspace...
          </div>
        )}

        <form onSubmit={handleSave} className="space-y-4">
          <div>
            <label htmlFor="api-key-input" className="block text-xs font-semibold text-gray-300 mb-1.5">
              API Key (X-API-Key)
            </label>
            <input
              id="api-key-input"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Enter your secret API key..."
              className="w-full px-3.5 py-2.5 rounded-lg bg-gray-950 border border-gray-800 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 font-mono"
            />
            <span className="text-[11px] text-gray-500 mt-1 block">
              Stored locally in browser storage and securely transmitted in the <code>X-API-Key</code> request header.
            </span>
          </div>

          <div className="bg-gray-950 p-3.5 rounded-lg border border-gray-800 text-xs text-gray-400 space-y-1.5">
            <div className="flex items-center gap-2 text-gray-300 font-semibold">
              <Shield className="w-4 h-4 text-blue-400" /> Security Invariants
            </div>
            <div>• Production endpoints fail-closed without an authenticated key.</div>
            <div>• All transactions enforce timing-safe cryptographic comparisons.</div>
          </div>

          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg text-xs font-semibold transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all shadow-md shadow-blue-600/20"
            >
              <Save className="w-4 h-4" /> Save Settings
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
