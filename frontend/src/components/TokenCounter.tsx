import React, { useEffect, useState } from 'react';
import type { TokenUsageData } from '../types';

interface TokenCounterProps {
  tokenUsage: TokenUsageData;
}

export const TokenCounter: React.FC<TokenCounterProps> = ({ tokenUsage }) => {
  const [isRolling, setIsRolling] = useState(false);
  const [displayTokens, setDisplayTokens] = useState(tokenUsage);

  useEffect(() => {
    if (
      tokenUsage.total_tokens !== displayTokens.total_tokens ||
      tokenUsage.total_input_tokens !== displayTokens.total_input_tokens ||
      tokenUsage.total_output_tokens !== displayTokens.total_output_tokens
    ) {
      setIsRolling(true);
      
      // Animate the token count update
      const startTime = Date.now();
      const duration = 800;
      const startTokens = displayTokens;
      const targetTokens = tokenUsage;
      
      const animate = () => {
        const elapsed = Date.now() - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const easedProgress = 1 - Math.pow(1 - progress, 2.5);
        
        const animatedTokens = {
          total_tokens: Math.floor(
            startTokens.total_tokens + 
            (targetTokens.total_tokens - startTokens.total_tokens) * easedProgress
          ),
          total_input_tokens: Math.floor(
            startTokens.total_input_tokens + 
            (targetTokens.total_input_tokens - startTokens.total_input_tokens) * easedProgress
          ),
          total_output_tokens: Math.floor(
            startTokens.total_output_tokens + 
            (targetTokens.total_output_tokens - startTokens.total_output_tokens) * easedProgress
          ),
        };
        
        setDisplayTokens(animatedTokens);
        
        if (progress < 1) {
          requestAnimationFrame(animate);
        } else {
          setDisplayTokens(targetTokens);
          setIsRolling(false);
        }
      };
      
      requestAnimationFrame(animate);
    }
  }, [tokenUsage, displayTokens]);

  return (
    <div className="bg-gradient-to-br from-surface to-border border border-border-hover rounded-lg px-3 py-2 font-mono font-medium">
      <div className="text-muted text-xs font-medium mb-0.5 uppercase tracking-wide">
        Tokens
      </div>
      
      <div className="flex items-center justify-center">
        <div className="bg-background border border-border rounded px-2 py-1 min-w-[70px]">
          <div className={`text-primary text-sm font-semibold text-center tabular-nums ${
            isRolling ? 'token-rolling' : ''
          }`}>
            {displayTokens.total_tokens.toLocaleString()}
          </div>
        </div>
      </div>
      
      <div className="flex gap-2 mt-0.5 text-xs">
        <span className="flex items-center gap-1 text-primary-hover">
          ↑ <span className="tabular-nums">{displayTokens.total_input_tokens.toLocaleString()}</span>
        </span>
        <span className="flex items-center gap-1 text-secondary">
          ↓ <span className="tabular-nums">{displayTokens.total_output_tokens.toLocaleString()}</span>
        </span>
      </div>
    </div>
  );
};
