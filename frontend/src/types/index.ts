// Socket.IO Event Types
export interface ServerToClientEvents {
  connect: () => void;
  disconnect: () => void;
  session_started: (data: { session_id: string }) => void;
  auto_confirm_state: (data: { enabled: boolean }) => void;
  message: (data: MessageData) => void;
  message_chunk: (data: MessageChunkData) => void;
  message_complete: (data: MessageData) => void;
  tool_confirmation: (data: ToolConfirmationData) => void;
  tool_execution_start: (data: ToolExecutionStartData) => void;
  tool_execution_result: (data: ToolExecutionResultData) => void;
  token_usage_update: (data: TokenUsageData) => void;
  rag_index_progress: (data: RagProgressData) => void;
  error: (data: { message: string }) => void;
}

export interface ClientToServerEvents {
  user_message: (data: { message: string; files?: FileContent[] }) => void;
  tool_confirm: (data: ToolConfirmData) => void;
  update_auto_confirm: (data: { enabled: boolean }) => void;
  get_auto_confirm_state: () => void;
}

// Message Types
export interface MessageData {
  type: 'user' | 'agent' | 'system' | 'error';
  content: string;
  timestamp: string;
}

export interface MessageChunkData {
  type: 'agent';
  chunk: string;
  timestamp: string;
}

// Tool Types
export interface ToolConfirmationData {
  tool_call_id: string;
  tool_name: string;
  tool_input: Record<string, any>;
  tool_call: any;
}

export interface ToolConfirmData {
  tool_call_id: string;
  confirmed: boolean;
  tool_call: any;
  rejection_reason?: string;
}

export interface ToolExecutionStartData {
  tool_name: string;
  code?: string;
  language?: string;
  timestamp: string;
}

export interface ToolExecutionResultData {
  result: string;
  plots?: string[];
}

// File Types
export interface FileContent {
  name: string;
  type: 'text' | 'image' | 'binary';
  content?: string;
  file_id?: string;
}

// Token Usage Types
export interface TokenUsageData {
  total_tokens: number;
  total_input_tokens: number;
  total_output_tokens: number;
}

// RAG Progress Types
export interface RagProgressData {
  progress: number;
  message: string;
}

// Conversation History Types
export interface ConversationHistory {
  started_at: string;
  history: MessageData[];
}

// App State Types
export interface AppState {
  isConnected: boolean;
  autoConfirmEnabled: boolean;
  isTyping: boolean;
  currentStreamingMessage: MessageData | null;
  tokenUsage: TokenUsageData;
  messages: MessageData[];
  toolExecutions: ToolExecutionData[];
  toolConfirmations: ToolConfirmationData[];
  ragProgress: RagProgressData | null;
}

export interface ToolExecutionData {
  id: string;
  toolName: string;
  code?: string;
  language?: string;
  result?: string;
  plots?: string[];
  timestamp: string;
  isComplete: boolean;
}

// Component Props Types
export interface MessageListProps {
  messages: MessageData[];
  toolExecutions: ToolExecutionData[];
  toolConfirmations: ToolConfirmationData[];
  currentStreamingMessage: MessageData | null;
  ragProgress: RagProgressData | null;
  isTyping: boolean;
  onToolConfirm: (data: ToolConfirmData) => void;
}

export interface MessageInputProps {
  onSendMessage: (message: string, files?: FileContent[]) => void;
  disabled: boolean;
}

export interface HeaderProps {
  isConnected: boolean;
  autoConfirmEnabled: boolean;
  tokenUsage: TokenUsageData;
  onToggleAutoConfirm: () => void;
  onShowHistory: () => void;
}

export interface HistoryPanelProps {
  isOpen: boolean;
  onClose: () => void;
  onLoadConversation: (conversation: ConversationHistory) => void;
}
