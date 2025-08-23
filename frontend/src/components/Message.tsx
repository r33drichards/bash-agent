import React from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import type { MessageData } from '../types';

interface MessageProps {
  message: MessageData;
  isStreaming?: boolean;
}

export const Message: React.FC<MessageProps> = ({ message, isStreaming }) => {
  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString();
  };

  const getTypeLabel = (type: string) => {
    switch (type) {
      case 'user': return 'You';
      case 'agent': return 'Agent';
      case 'system': return 'System';
      case 'error': return 'Error';
      default: return type;
    }
  };

  const getTypeStyles = (type: string) => {
    switch (type) {
      case 'user':
        return 'text-primary';
      case 'agent':
        return 'text-text';
      case 'system':
        return 'text-muted italic';
      case 'error':
        return 'text-danger bg-surface border border-danger px-3 py-2 rounded-md border-l-4';
      default:
        return 'text-text';
    }
  };

  return (
    <div className={`mb-4 ${getTypeStyles(message.type)}`}>
      <div className="flex items-center mb-1 text-sm font-semibold">
        <span>{getTypeLabel(message.type)}</span>
        <span className="text-muted text-xs ml-2">
          {formatTime(message.timestamp)}
        </span>
      </div>
      
      <div className="text-sm leading-relaxed">
        {message.type === 'agent' ? (
          <div className="prose prose-sm max-w-none">
            <ReactMarkdown rehypePlugins={[rehypeHighlight]}>
              {message.content}
            </ReactMarkdown>
            {isStreaming && <span className="streaming-cursor ml-0.5">▎</span>}
          </div>
        ) : (
          <div className="whitespace-pre-wrap break-words">
            {message.content}
            {isStreaming && <span className="streaming-cursor ml-0.5">▎</span>}
          </div>
        )}
      </div>
    </div>
  );
};
