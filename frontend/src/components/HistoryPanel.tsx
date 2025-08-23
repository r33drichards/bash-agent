import React, { useState, useEffect } from 'react';
import { X } from 'lucide-react';
import type { HistoryPanelProps, ConversationHistory } from '../types';

export const HistoryPanel: React.FC<HistoryPanelProps> = ({
  isOpen,
  onClose,
  onLoadConversation,
}) => {
  const [conversations, setConversations] = useState<ConversationHistory[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      loadConversationHistory();
    }
  }, [isOpen]);

  const loadConversationHistory = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch('/api/conversation-history');
      if (!response.ok) {
        throw new Error('Failed to load conversation history');
      }
      
      const history = await response.json();
      setConversations(history);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      console.error('Error loading conversation history:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleLoadConversation = (conversation: ConversationHistory) => {
    onLoadConversation(conversation);
    onClose();
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return `${date.toLocaleDateString()} ${date.toLocaleTimeString()}`;
  };

  const getConversationPreview = (conversation: ConversationHistory) => {
    const firstUserMessage = conversation.history.find(msg => msg.type === 'user');
    return firstUserMessage 
      ? firstUserMessage.content.substring(0, 100) + '...'
      : 'No user messages';
  };

  if (!isOpen) return null;

  return (
    <>
      {/* Overlay */}
      <div 
        className="fixed inset-0 bg-black/50 z-40"
        onClick={onClose}
      />
      
      {/* Panel */}
      <div className="fixed top-0 right-0 w-96 h-full bg-surface border-l border-border z-50 overflow-hidden flex flex-col">
        {/* Header */}
        <div className="bg-background px-4 py-4 border-b border-border flex items-center justify-between">
          <h2 className="text-text-bright text-lg font-semibold">
            Conversation History
          </h2>
          <button
            onClick={onClose}
            className="text-muted hover:text-text p-1 rounded transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        
        {/* Content */}
        <div className="flex-1 overflow-y-auto scrollbar-custom">
          {loading && (
            <div className="p-5 text-center text-muted">
              Loading conversations...
            </div>
          )}
          
          {error && (
            <div className="p-5 text-center text-danger">
              <p className="mb-3">{error}</p>
              <button
                onClick={loadConversationHistory}
                className="bg-border hover:bg-border-hover text-text px-3 py-1 rounded text-sm transition-colors"
              >
                Retry
              </button>
            </div>
          )}
          
          {!loading && !error && conversations.length === 0 && (
            <div className="p-5 text-center text-muted">
              No conversation history found
            </div>
          )}
          
          {!loading && !error && conversations.length > 0 && (
            <div>
              {conversations.map((conversation, index) => (
                <div
                  key={index}
                  onClick={() => handleLoadConversation(conversation)}
                  className="p-3 border-b border-border cursor-pointer hover:bg-background transition-colors"
                >
                  <div className="text-muted text-xs mb-1">
                    {formatDate(conversation.started_at)}
                  </div>
                  <div className="text-text text-sm leading-relaxed">
                    {getConversationPreview(conversation)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
};
