import React from 'react';
import { Search } from 'lucide-react';
import type { RagProgressData } from '../types';

interface RagProgressProps {
  progress: RagProgressData;
}

export const RagProgress: React.FC<RagProgressProps> = ({ progress }) => {
  return (
    <div className="bg-surface border border-border rounded-lg p-4 mb-4">
      <div className="flex items-center gap-2 text-primary font-semibold mb-3">
        <Search className="w-4 h-4" />
        Indexing Repository
      </div>
      
      <div className="bg-background border border-border rounded-md h-2 overflow-hidden mb-2">
        <div 
          className="h-full bg-gradient-to-r from-secondary to-secondary/80 transition-all duration-300 rounded-md"
          style={{ width: `${progress.progress}%` }}
        />
      </div>
      
      <div className="text-muted text-xs">
        {progress.message}
      </div>
    </div>
  );
};
