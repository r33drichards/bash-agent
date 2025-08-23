import React, { useRef } from 'react';
import { Upload, X, File, Image } from 'lucide-react';
import type { FileContent } from '../types';

interface FileUploadProps {
  files: FileContent[];
  onFilesAdd: (files: FileList) => Promise<void>;
  onFileRemove: (index: number) => void;
  isUploading?: boolean;
}

export const FileUpload: React.FC<FileUploadProps> = ({
  files,
  onFilesAdd,
  onFileRemove,
  isUploading = false,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = event.target.files;
    if (selectedFiles && selectedFiles.length > 0) {
      onFilesAdd(selectedFiles);
    }
    // Reset input to allow selecting the same file again
    event.target.value = '';
  };

  const handleDrop = (event: React.DragEvent) => {
    event.preventDefault();
    const droppedFiles = event.dataTransfer.files;
    if (droppedFiles.length > 0) {
      onFilesAdd(droppedFiles);
    }
  };

  const handleDragOver = (event: React.DragEvent) => {
    event.preventDefault();
  };

  const getFileIcon = (file: FileContent) => {
    if (file.type === 'image') {
      return <Image className="w-4 h-4" />;
    }
    return <File className="w-4 h-4" />;
  };

  const renderFilePreview = (file: FileContent) => {
    if (file.type === 'image' && file.content) {
      return (
        <img
          src={file.content}
          alt={file.name}
          className="w-16 h-16 object-cover rounded border border-border"
        />
      );
    }
    return null;
  };

  return (
    <div className="space-y-3">
      {/* File input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        onChange={handleFileChange}
        className="hidden"
      />

      {/* Drop zone */}
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onClick={handleFileClick}
        className="border-2 border-dashed border-border hover:border-primary transition-colors rounded-lg p-6 text-center cursor-pointer bg-background hover:bg-surface"
      >
        <Upload className="w-8 h-8 mx-auto mb-2 text-muted" />
        <p className="text-sm text-text">
          {isUploading ? (
            'Uploading files...'
          ) : (
            <>
              Drop files here or <span className="text-primary">browse</span>
            </>
          )}
        </p>
        <p className="text-xs text-muted mt-1">
          Supports images, text files, and documents
        </p>
      </div>

      {/* Attached files list */}
      {files.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-primary">Attached Files:</h4>
          <div className="grid gap-2">
            {files.map((file, index) => (
              <div
                key={index}
                className="flex items-center gap-3 bg-surface border border-border rounded-lg p-3"
              >
                {getFileIcon(file)}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-text truncate">
                    {file.name}
                  </p>
                  {file.type === 'text' && file.content && (
                    <p className="text-xs text-muted truncate">
                      {file.content.substring(0, 50)}...
                    </p>
                  )}
                </div>
                {renderFilePreview(file)}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onFileRemove(index);
                  }}
                  className="text-danger hover:text-danger-hover p-1 rounded transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
