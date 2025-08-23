import React from 'react';
import { Wrench } from 'lucide-react';
import type { ToolExecutionData } from '../types';

interface ToolExecutionProps {
  execution: ToolExecutionData;
}

export const ToolExecution: React.FC<ToolExecutionProps> = ({ execution }) => {
  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString();
  };

  return (
    <div className="bg-surface border border-border rounded-lg mb-4 overflow-hidden">
      {/* Header */}
      <div className="bg-border px-4 py-3 border-b border-border-hover flex items-center gap-2 font-semibold text-text-bright text-sm">
        <Wrench className="w-4 h-4" />
        {execution.toolName.toUpperCase()} Tool Execution
        <span className="text-muted text-xs ml-auto">
          {formatTime(execution.timestamp)}
        </span>
      </div>

      {/* Code Section */}
      {execution.code && (
        <div className="bg-background px-4 py-4 border-b border-border">
          <div className="text-secondary font-semibold mb-2 text-sm">
            Code:
          </div>
          <pre className="bg-surface border border-border rounded-md p-3 overflow-x-auto text-sm font-mono">
            <code className={`language-${execution.language || 'plaintext'}`}>
              {execution.code}
            </code>
          </pre>
        </div>
      )}

      {/* Result Section */}
      {execution.isComplete && execution.result && (
        <div className="bg-background px-4 py-4">
          <div className="text-primary font-semibold mb-2 text-sm">
            Result:
          </div>
          <pre className="bg-surface border border-border rounded-md p-3 overflow-x-auto text-sm font-mono whitespace-pre-wrap break-words text-text">
            {execution.result}
          </pre>
          
          {/* Plots */}
          {execution.plots && execution.plots.length > 0 && (
            <div className="mt-4">
              <div className="text-text-bright font-semibold mb-3 text-sm">
                📊 Generated Plots:
              </div>
              {execution.plots.map((plotData, index) => (
                <img
                  key={index}
                  src={`data:image/png;base64,${plotData}`}
                  alt={`Plot ${index + 1}`}
                  className="max-w-full h-auto rounded-md border border-border mb-3 bg-white"
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
