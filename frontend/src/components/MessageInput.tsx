import React, { useState, useRef, useCallback, useEffect } from 'react';
import { Send, Paperclip } from 'lucide-react';
import { FileUpload } from './FileUpload';
import { useFileUpload } from '../hooks/useFileUpload';
import type { MessageInputProps } from '../types';

export const MessageInput: React.FC<MessageInputProps> = ({
  onSendMessage,
  disabled,
}) => {
  const [message, setMessage] = useState('');
  const [showFileUpload, setShowFileUpload] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  
  const {
    attachedFiles,
    isUploading,
    addFiles,
    removeFile,
    clearFiles,
  } = useFileUpload();

  // Auto-resize textarea
  const adjustTextareaHeight = useCallback(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      const newHeight = Math.min(textarea.scrollHeight, 200); // Max height of 200px
      textarea.style.height = `${newHeight}px`;
    }
  }, []);

  useEffect(() => {
    adjustTextareaHeight();
  }, [message, adjustTextareaHeight]);

  const handleSend = useCallback(() => {
    const trimmedMessage = message.trim();
    if (trimmedMessage && !disabled) {
      onSendMessage(trimmedMessage, attachedFiles.length > 0 ? attachedFiles : undefined);
      setMessage('');
      clearFiles();
      setShowFileUpload(false);
    }
  }, [message, attachedFiles, disabled, onSendMessage, clearFiles]);

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  const handlePaste = async (event: React.ClipboardEvent) => {
    const items = event.clipboardData.items;
    const files: File[] = [];
    
    for (const item of Array.from(items)) {
      if (item.kind === 'file') {
        const file = item.getAsFile();
        if (file) {
          files.push(file);
        }
      }
    }
    
    if (files.length > 0) {
      event.preventDefault();
      const fileList = new DataTransfer();
      files.forEach(file => fileList.items.add(file));
      
      setShowFileUpload(true);
      await addFiles(fileList.files);
    }
  };

  const handleFilesAdd = async (files: FileList) => {
    try {
      await addFiles(files);
    } catch (error) {
      console.error('Error adding files:', error);
    }
  };

  const toggleFileUpload = () => {
    setShowFileUpload(!showFileUpload);
  };

  return (
    <div className="bg-surface border-t border-border p-5">
      {/* File upload section */}
      {showFileUpload && (
        <div className="mb-4">
          <FileUpload
            files={attachedFiles}
            onFilesAdd={handleFilesAdd}
            onFileRemove={removeFile}
            isUploading={isUploading}
          />
        </div>
      )}

      {/* Input area */}
      <div className="flex items-end gap-3">
        <div className="flex-1 relative">
          <textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder="Type your message here... (Paste images with Cmd/Ctrl+V)"
            disabled={disabled}
            className="w-full bg-background border border-border text-text px-4 py-3 text-sm font-mono rounded-md resize-none focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ minHeight: '44px' }}
            rows={1}
          />
        </div>
        
        <button
          onClick={toggleFileUpload}
          className={`p-3 text-sm font-semibold rounded-md transition-colors ${
            showFileUpload
              ? 'bg-border-hover text-text'
              : 'bg-border hover:bg-border-hover text-text'
          }`}
          disabled={disabled}
        >
          <Paperclip className="w-4 h-4" />
        </button>
        
        <button
          onClick={handleSend}
          disabled={disabled || !message.trim()}
          className="bg-secondary hover:bg-secondary/80 disabled:bg-border disabled:text-muted text-background px-5 py-3 text-sm font-semibold rounded-md transition-colors flex items-center gap-2"
        >
          <Send className="w-4 h-4" />
          Send
        </button>
      </div>
      
      {/* File count indicator */}
      {attachedFiles.length > 0 && (
        <div className="mt-2 text-xs text-muted">
          {attachedFiles.length} file{attachedFiles.length !== 1 ? 's' : ''} attached
        </div>
      )}
    </div>
  );
};
