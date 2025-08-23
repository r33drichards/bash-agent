import React from 'react';
import { History } from 'lucide-react';
import type { HeaderProps } from '../types';
import { TokenCounter } from './TokenCounter';
import { ToggleSwitch } from './ToggleSwitch';

export const Header: React.FC<HeaderProps> = ({
  isConnected,
  autoConfirmEnabled,
  tokenUsage,
  onToggleAutoConfirm,
  onShowHistory,
}) => {
  return (
    <header className="bg-surface border-b border-border px-5 py-3 flex items-center justify-between">
      <div className="text-text-bright text-base font-semibold">
        Claude Code Agent
      </div>
      
      <div className="flex items-center gap-4">
        <TokenCounter tokenUsage={tokenUsage} />
        
        <button
          onClick={onShowHistory}
          className="bg-border hover:bg-border-hover text-text border border-border-hover px-4 py-2 text-xs font-semibold rounded-md transition-colors"
        >
          <History className="w-3 h-3 mr-2 inline-block" />
          History
        </button>
        
        <div className="flex items-center gap-2">
          <span className="text-xs text-text">Auto-confirm</span>
          <ToggleSwitch
            checked={autoConfirmEnabled}
            onChange={onToggleAutoConfirm}
          />
        </div>
        
        <div className="flex items-center gap-2 text-muted text-xs">
          <div className={`w-2 h-2 rounded-full ${
            isConnected ? 'bg-secondary' : 'bg-danger'
          }`} />
          <span>{isConnected ? 'Connected' : 'Disconnected'}</span>
        </div>
      </div>
    </header>
  );
};
