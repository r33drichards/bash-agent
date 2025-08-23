import React, { useEffect, useRef } from 'react';
import { Message } from './Message';
import { ToolExecution } from './ToolExecution';
import { ToolConfirmation } from './ToolConfirmation';
import { RagProgress } from './RagProgress';
import type { MessageListProps } from '../types';

export const MessageList: React.FC<MessageListProps> = ({
  messages,
  toolExecutions,
  toolConfirmations,
  currentStreamingMessage,
  ragProgress,
  isTyping,
  onToolConfirm,
}) => {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, toolExecutions, toolConfirmations, currentStreamingMessage, ragProgress]);

  // Combine and sort all content by timestamp
  const allContent = [
    ...messages.map(msg => ({ type: 'message', data: msg, timestamp: msg.timestamp })),
    ...toolExecutions.map(exec => ({ type: 'tool_execution', data: exec, timestamp: exec.timestamp })),
  ].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

  return (
    <div className="flex-1 overflow-y-auto px-5 py-5 scrollbar-custom">
      {/* Render sorted content */}
      {allContent.map((item, index) => {
        if (item.type === 'message') {
          return (
            <Message
              key={`message-${index}`}
              message={item.data as any}
            />
          );
        } else if (item.type === 'tool_execution') {
          return (
            <ToolExecution
              key={`tool-${index}`}
              execution={item.data as any}
            />
          );
        }
        return null;
      })}

      {/* Current streaming message */}
      {currentStreamingMessage && (
        <Message
          message={currentStreamingMessage}
          isStreaming
        />
      )}

      {/* Tool confirmations */}
      {toolConfirmations.map((confirmation) => (
        <ToolConfirmation
          key={confirmation.tool_call_id}
          confirmation={confirmation}
          onConfirm={onToolConfirm}
        />
      ))}

      {/* RAG progress */}
      {ragProgress && (
        <RagProgress progress={ragProgress} />
      )}

      {/* Typing indicator */}
      {isTyping && !currentStreamingMessage && toolConfirmations.length === 0 && (
        <div className="text-muted italic text-sm mb-4">
          Agent is typing...
        </div>
      )}

      {/* Empty state */}
      {allContent.length === 0 && !currentStreamingMessage && !isTyping && (
        <div className="flex-1 flex items-center justify-center text-muted text-center">
          <div>
            <div className="text-4xl mb-4">🤖</div>
            <div className="text-lg font-semibold mb-2">Welcome to Claude Code Agent</div>
            <div className="text-sm">
              Type a message below to start a conversation.
            </div>
          </div>
        </div>
      )}

      <div ref={messagesEndRef} />
    </div>
  );
};
