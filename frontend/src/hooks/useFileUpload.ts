import { useState, useCallback } from 'react';
import type { FileContent } from '../types';

export const useFileUpload = () => {
  const [attachedFiles, setAttachedFiles] = useState<FileContent[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  const uploadFiles = useCallback(async (files: FileList): Promise<FileContent[]> => {
    setIsUploading(true);
    const uploadedFiles: FileContent[] = [];

    try {
      for (const file of Array.from(files)) {
        const fileContent = await processFile(file);
        if (fileContent) {
          uploadedFiles.push(fileContent);
        }
      }
    } catch (error) {
      console.error('Error uploading files:', error);
      throw error;
    } finally {
      setIsUploading(false);
    }

    return uploadedFiles;
  }, []);

  const processFile = async (file: File): Promise<FileContent | null> => {
    const isImage = file.type.startsWith('image/');
    const isText = file.type.startsWith('text/') || 
                   file.name.endsWith('.md') ||
                   file.name.endsWith('.json') ||
                   file.name.endsWith('.xml') ||
                   file.name.endsWith('.css') ||
                   file.name.endsWith('.js') ||
                   file.name.endsWith('.ts') ||
                   file.name.endsWith('.jsx') ||
                   file.name.endsWith('.tsx');

    if (isImage) {
      return new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => {
          resolve({
            name: file.name,
            type: 'image',
            content: reader.result as string,
          });
        };
        reader.onerror = () => resolve(null);
        reader.readAsDataURL(file);
      });
    } else if (isText && file.size < 1024 * 1024) { // 1MB limit for text files
      return new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => {
          resolve({
            name: file.name,
            type: 'text',
            content: reader.result as string,
          });
        };
        reader.onerror = () => resolve(null);
        reader.readAsText(file);
      });
    } else {
      // For large files or binary files, upload to server first
      try {
        const formData = new FormData();
        formData.append('files', file);
        
        const response = await fetch('/api/upload', {
          method: 'POST',
          body: formData,
        });
        
        const data = await response.json();
        
        if (data.success && data.files && data.files.length > 0) {
          return data.files[0];
        }
      } catch (error) {
        console.error('Error uploading file to server:', error);
      }
      
      return null;
    }
  };

  const addFiles = useCallback(async (files: FileList) => {
    const newFiles = await uploadFiles(files);
    setAttachedFiles(prev => [...prev, ...newFiles]);
    return newFiles;
  }, [uploadFiles]);

  const removeFile = useCallback((index: number) => {
    setAttachedFiles(prev => prev.filter((_, i) => i !== index));
  }, []);

  const clearFiles = useCallback(() => {
    setAttachedFiles([]);
  }, []);

  return {
    attachedFiles,
    isUploading,
    addFiles,
    removeFile,
    clearFiles,
  };
};
