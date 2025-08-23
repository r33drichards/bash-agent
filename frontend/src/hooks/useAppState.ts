import { useState, useCallback, useEffect } from 'react';
import type { 
  AppState, 
  MessageData, 
  ToolExecutionData, 
  ToolExecutionStartData,
  ToolConfirmationData, 
  TokenUsageData,
  RagProgressData,
  ConversationHistory,
  ToolConfirmData,
  FileContent
} from '../types';
import { useSocket } from './useSocket';

const initialTokenUsage: TokenUsageData = {
  total_tokens: 0,
  total_input_tokens: 0,
  total_output_tokens: 0,
};

const initialState: AppState = {
  isConnected: false,
  autoConfirmEnabled: false,
  isTyping: false,
  currentStreamingMessage: null,
  tokenUsage: initialTokenUsage,
  messages: [],
  toolExecutions: [],
  toolConfirmations: [],
  ragProgress: null,
};

export const useAppState = () => {
  const [state, setState] = useState<AppState>(initialState);
  const { socket, isConnected } = useSocket();

  // Update connection state
  useEffect(() => {
    setState(prev => ({ ...prev, isConnected }));
  }, [isConnected]);

  // Socket event handlers
  useEffect(() => {
    if (!socket) return;

    const handleSessionStarted = (data: { session_id: string }) => {
      console.log('Session started:', data.session_id);
      socket.emit('get_auto_confirm_state');
    };

    const handleAutoConfirmState = (data: { enabled: boolean }) => {
      setState(prev => ({ ...prev, autoConfirmEnabled: data.enabled }));
    };

    const handleMessage = (data: MessageData) => {
      setState(prev => ({
        ...prev,
        messages: [...prev.messages, data],
        isTyping: false,
      }));
    };

    const handleMessageChunk = (data: { type: 'agent'; chunk: string; timestamp: string }) => {
      setState(prev => {
        if (!prev.currentStreamingMessage) {
          return {
            ...prev,
            currentStreamingMessage: {
              type: 'agent',
              content: data.chunk,
              timestamp: data.timestamp,
            },
            isTyping: false,
          };
        }
        return {
          ...prev,
          currentStreamingMessage: {
            ...prev.currentStreamingMessage,
            content: prev.currentStreamingMessage.content + data.chunk,
          },
        };
      });
    };

    const handleMessageComplete = (data: MessageData) => {
      setState(prev => ({
        ...prev,
        messages: [...prev.messages, data],
        currentStreamingMessage: null,
      }));
    };

    const handleToolConfirmation = (data: ToolConfirmationData) => {
      setState(prev => ({
        ...prev,
        toolConfirmations: [...prev.toolConfirmations, data],
        isTyping: false,
      }));
    };

    const handleToolExecutionStart = (data: ToolExecutionStartData) => {
      const toolExecution: ToolExecutionData = {
        id: `tool-${Date.now()}`,
        toolName: data.tool_name,
        code: data.code,
        language: data.language,
        timestamp: data.timestamp,
        isComplete: false,
      };
      
      setState(prev => ({
        ...prev,
        toolExecutions: [...prev.toolExecutions, toolExecution],
        isTyping: false,
      }));
    };

    const handleToolExecutionResult = (data: { result: string; plots?: string[] }) => {
      setState(prev => {
        const updatedExecutions = prev.toolExecutions.map(exec => {
          if (!exec.isComplete && !exec.result) {
            return {
              ...exec,
              result: data.result,
              plots: data.plots,
              isComplete: true,
            };
          }
          return exec;
        });
        
        return {
          ...prev,
          toolExecutions: updatedExecutions,
        };
      });
    };

    const handleTokenUsageUpdate = (data: TokenUsageData) => {
      setState(prev => ({ ...prev, tokenUsage: data }));
    };

    const handleRagProgress = (data: RagProgressData) => {
      setState(prev => ({ ...prev, ragProgress: data }));
      
      // Clear progress after completion
      if (data.progress >= 100) {
        setTimeout(() => {
          setState(prev => ({ ...prev, ragProgress: null }));
        }, 2000);
      }
    };

    const handleError = (data: { message: string }) => {
      const errorMessage: MessageData = {
        type: 'error',
        content: data.message,
        timestamp: new Date().toISOString(),
      };
      setState(prev => ({
        ...prev,
        messages: [...prev.messages, errorMessage],
        isTyping: false,
      }));
    };

    // Register event listeners
    socket.on('session_started', handleSessionStarted);
    socket.on('auto_confirm_state', handleAutoConfirmState);
    socket.on('message', handleMessage);
    socket.on('message_chunk', handleMessageChunk);
    socket.on('message_complete', handleMessageComplete);
    socket.on('tool_confirmation', handleToolConfirmation);
    socket.on('tool_execution_start', handleToolExecutionStart);
    socket.on('tool_execution_result', handleToolExecutionResult);
    socket.on('token_usage_update', handleTokenUsageUpdate);
    socket.on('rag_index_progress', handleRagProgress);
    socket.on('error', handleError);

    // Cleanup
    return () => {
      socket.off('session_started', handleSessionStarted);
      socket.off('auto_confirm_state', handleAutoConfirmState);
      socket.off('message', handleMessage);
      socket.off('message_chunk', handleMessageChunk);
      socket.off('message_complete', handleMessageComplete);
      socket.off('tool_confirmation', handleToolConfirmation);
      socket.off('tool_execution_start', handleToolExecutionStart);
      socket.off('tool_execution_result', handleToolExecutionResult);
      socket.off('token_usage_update', handleTokenUsageUpdate);
      socket.off('rag_index_progress', handleRagProgress);
      socket.off('error', handleError);
    };
  }, [socket]);

  // Actions
  const sendMessage = useCallback((message: string, files?: FileContent[]) => {
    if (socket && isConnected && message.trim()) {
      socket.emit('user_message', { message, files });
      setState(prev => ({ ...prev, isTyping: true }));
      
      // Add user message to local state immediately
      const userMessage: MessageData = {
        type: 'user',
        content: message,
        timestamp: new Date().toISOString(),
      };
      setState(prev => ({
        ...prev,
        messages: [...prev.messages, userMessage],
      }));
    }
  }, [socket, isConnected]);

  const confirmTool = useCallback((data: ToolConfirmData) => {
    if (socket) {
      socket.emit('tool_confirm', data);
      
      // Remove the confirmation from state
      setState(prev => ({
        ...prev,
        toolConfirmations: prev.toolConfirmations.filter(
          conf => conf.tool_call_id !== data.tool_call_id
        ),
        isTyping: data.confirmed,
      }));
    }
  }, [socket]);

  const toggleAutoConfirm = useCallback(() => {
    if (socket) {
      const newState = !state.autoConfirmEnabled;
      socket.emit('update_auto_confirm', { enabled: newState });
      setState(prev => ({ ...prev, autoConfirmEnabled: newState }));
    }
  }, [socket, state.autoConfirmEnabled]);

  const loadConversation = useCallback((conversation: ConversationHistory) => {
    setState(prev => ({
      ...prev,
      messages: conversation.history,
      toolExecutions: [],
      toolConfirmations: [],
      currentStreamingMessage: null,
      ragProgress: null,
    }));
  }, []);

  const clearMessages = useCallback(() => {
    setState(prev => ({
      ...prev,
      messages: [],
      toolExecutions: [],
      toolConfirmations: [],
      currentStreamingMessage: null,
      ragProgress: null,
    }));
  }, []);

  return {
    ...state,
    actions: {
      sendMessage,
      confirmTool,
      toggleAutoConfirm,
      loadConversation,
      clearMessages,
    },
  };
};
