import { useState } from 'react';
import { Header } from './components/Header';
import { MessageList } from './components/MessageList';
import { MessageInput } from './components/MessageInput';
import { HistoryPanel } from './components/HistoryPanel';
import { useAppState } from './hooks/useAppState';
import './App.css';

function App() {
  const [showHistory, setShowHistory] = useState(false);
  const {
    isConnected,
    autoConfirmEnabled,
    isTyping,
    currentStreamingMessage,
    tokenUsage,
    messages,
    toolExecutions,
    toolConfirmations,
    ragProgress,
    actions,
  } = useAppState();

  const handleShowHistory = () => {
    setShowHistory(true);
  };

  const handleCloseHistory = () => {
    setShowHistory(false);
  };

  return (
    <div className="h-screen bg-background text-text font-mono flex flex-col">
      <Header
        isConnected={isConnected}
        autoConfirmEnabled={autoConfirmEnabled}
        tokenUsage={tokenUsage}
        onToggleAutoConfirm={actions.toggleAutoConfirm}
        onShowHistory={handleShowHistory}
      />
      
      <div className="flex-1 flex flex-col overflow-hidden">
        <MessageList
          messages={messages}
          toolExecutions={toolExecutions}
          toolConfirmations={toolConfirmations}
          currentStreamingMessage={currentStreamingMessage}
          ragProgress={ragProgress}
          isTyping={isTyping}
          onToolConfirm={actions.confirmTool}
        />
        
        <MessageInput
          onSendMessage={actions.sendMessage}
          disabled={!isConnected}
        />
      </div>
      
      <HistoryPanel
        isOpen={showHistory}
        onClose={handleCloseHistory}
        onLoadConversation={actions.loadConversation}
      />
    </div>
  );
}

export default App;
