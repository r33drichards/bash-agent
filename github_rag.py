#!/usr/bin/env python3
"""
GitHub RAG Tool - Integration for bash-agent to index and query GitHub repositories.
"""

import os
import sys
import tempfile
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)

class GitHubRAG:
    """GitHub Repository RAG (Retrieval Augmented Generation) system."""
    
    def __init__(self, openai_api_key: str, persist_directory: str = "./rag_storage"):
        """Initialize the GitHub RAG system."""
        # Remove ensure_dependencies logic
        from langchain_openai import OpenAIEmbeddings, ChatOpenAI
        from langchain_chroma import Chroma
        
        self.openai_api_key = openai_api_key
        self.persist_directory = persist_directory
        self.embeddings = OpenAIEmbeddings(openai_api_key=openai_api_key)
        self.llm = ChatOpenAI(openai_api_key=openai_api_key, model_name="gpt-3.5-turbo", temperature=0)
        self.repositories = {}  # Track indexed repositories
        
        # Create persist directory with proper permissions
        os.makedirs(persist_directory, exist_ok=True)
        # Ensure the directory is writable
        os.chmod(persist_directory, 0o755)
        
        # Load existing repositories
        self._load_repository_index()
    
    def _load_repository_index(self):
        """Load the index of existing repositories."""
        index_file = os.path.join(self.persist_directory, "repo_index.json")
        if os.path.exists(index_file):
            try:
                with open(index_file, 'r') as f:
                    self.repositories = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load repository index: {e}")
                self.repositories = {}
    
    def _save_repository_index(self):
        """Save the repository index."""
        index_file = os.path.join(self.persist_directory, "repo_index.json")
        try:
            with open(index_file, 'w') as f:
                json.dump(self.repositories, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save repository index: {e}")
    
    def clone_github_repo(self, repo_url: str, target_dir: str, shallow: bool = True) -> str:
        """Clone a GitHub repository."""
        logger.info(f"Cloning repository: {repo_url}")
        
        os.makedirs(target_dir, exist_ok=True)
        repo_name = repo_url.split('/')[-1].replace('.git', '')
        repo_path = os.path.join(target_dir, repo_name)
        
        clone_cmd = ['git', 'clone']
        if shallow:
            clone_cmd.extend(['--depth', '1'])
        clone_cmd.extend([repo_url, repo_path])
        
        subprocess.run(clone_cmd, check=True)
        logger.info(f"Repository cloned to: {repo_path}")
        
        return repo_path
    
    def should_process_file(self, file_path: str, ignore_dirs: List[str], include_extensions: Optional[List[str]], max_file_size: int = 100000) -> bool:
        """Determine if a file should be processed."""
        for ignore_dir in ignore_dirs:
            if f"/{ignore_dir}/" in file_path or file_path.startswith(f"{ignore_dir}/"):
                return False
        
        # Check file size
        try:
            if os.path.getsize(file_path) > max_file_size:
                logger.warning(f"Skipping large file {file_path} (size: {os.path.getsize(file_path)} bytes)")
                return False
        except OSError:
            return False
        
        if include_extensions:
            file_ext = os.path.splitext(file_path)[1].lower()
            if not file_ext or file_ext[1:] not in include_extensions:
                return False
        
        # Skip binary files by checking for common binary extensions
        binary_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.pdf', '.zip', '.tar', '.gz', '.exe', '.dll', '.so', '.dylib', '.woff', '.woff2', '.ttf', '.otf'}
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext in binary_extensions:
            return False
        
        return True
    
    def read_file_contents(self, file_path: str) -> str:
        """Read file contents with encoding fallback."""
        encodings = ['utf-8', 'latin-1', 'cp1252']
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
            except Exception as e:
                logger.warning(f"Error reading file {file_path}: {str(e)}")
                return ""
        
        logger.warning(f"Could not decode file {file_path}")
        return ""
    
    def get_repository_files(self, repo_path: str, ignore_dirs: List[str] = None, include_extensions: List[str] = None, max_file_size: int = 100000):
        """Get all files from a repository and convert them to documents."""
        from langchain_core.documents import Document
        
        if ignore_dirs is None:
            ignore_dirs = ['.git', 'node_modules', '__pycache__', '.idea', '.vscode', 'venv', '.env', 'target', 'build', 'dist']
        
        documents = []
        skipped_files = 0
        
        for root, _, files in os.walk(repo_path):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, repo_path)
                
                if self.should_process_file(file_path, ignore_dirs, include_extensions, max_file_size):
                    try:
                        content = self.read_file_contents(file_path)
                        if content and len(content.strip()) > 0:
                            doc = Document(
                                page_content=content,
                                metadata={
                                    "source": rel_path,
                                    "file_name": file,
                                    "file_path": rel_path,
                                }
                            )
                            documents.append(doc)
                    except Exception as e:
                        logger.warning(f"Error processing file {rel_path}: {str(e)}")
                        skipped_files += 1
                else:
                    skipped_files += 1
        
        logger.info(f"Processed {len(documents)} files from the repository (skipped {skipped_files} files)")
        return documents
    
    def split_documents(self, documents, chunk_size: int = 1000, chunk_overlap: int = 100):
        """Split documents into smaller chunks."""
        from langchain.text_splitter import RecursiveCharacterTextSplitter
        
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""]
        )
        
        chunked_docs = text_splitter.split_documents(documents)
        
        # Ensure all metadata values are strings for Chroma compatibility
        for doc in chunked_docs:
            for key in doc.metadata:
                doc.metadata[key] = str(doc.metadata[key])
        
        return chunked_docs
    
    def index_repository(self, repo_url: str, include_extensions: List[str] = None, ignore_dirs: List[str] = None, progress_callback=None, max_file_size: int = 100000, max_chunk_count: int = 5000, force_reindex: bool = False) -> Dict[str, Any]:
        """Index a GitHub repository for RAG queries."""
        from langchain_chroma import Chroma
        
        # Generate a collection name from the repo URL
        repo_name = repo_url.split('/')[-1].replace('.git', '')
        collection_name = f"repo_{repo_name}".replace('-', '_').replace('.', '_')
        
        # Check if already indexed
        if collection_name in self.repositories and not force_reindex:
            return {
                "success": True,
                "message": f"Repository {repo_name} is already indexed",
                "collection_name": collection_name,
                "repo_name": repo_name
            }
        
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                # Clone repository
                if progress_callback:
                    progress_callback({"step": "cloning", "progress": 10, "message": f"Cloning repository {repo_name}..."})
                repo_path = self.clone_github_repo(repo_url, temp_dir)
                
                # Get documents
                if progress_callback:
                    progress_callback({"step": "scanning", "progress": 25, "message": "Scanning repository files..."})
                documents = self.get_repository_files(repo_path, ignore_dirs, include_extensions, max_file_size)
                
                if not documents:
                    return {
                        "success": False,
                        "error": "No files found in repository"
                    }
                
                # Split documents
                if progress_callback:
                    progress_callback({"step": "chunking", "progress": 50, "message": f"Processing {len(documents)} files into chunks..."})
                chunked_docs = self.split_documents(documents)
                
                # Limit chunks to prevent token overflow
                if len(chunked_docs) > max_chunk_count:
                    logger.warning(f"Repository has {len(chunked_docs)} chunks, limiting to {max_chunk_count} to prevent token overflow")
                    chunked_docs = chunked_docs[:max_chunk_count]
                
                # Create vector store with batch processing to handle large repositories
                if progress_callback:
                    progress_callback({"step": "embedding", "progress": 75, "message": f"Generating embeddings for {len(chunked_docs)} chunks..."})
                
                # Process in batches to avoid memory issues
                batch_size = 100
                vector_store = None
                for i in range(0, len(chunked_docs), batch_size):
                    batch = chunked_docs[i:i + batch_size]
                    
                    if vector_store is None:
                        # First batch creates the vector store
                        vector_store = Chroma.from_documents(
                            documents=batch,
                            embedding=self.embeddings,
                            persist_directory=self.persist_directory,
                            collection_name=collection_name
                        )
                    else:
                        # Subsequent batches add to existing store
                        vector_store.add_documents(batch)
                    
                    if progress_callback:
                        progress = 75 + (20 * (i + batch_size) / len(chunked_docs))
                        progress_callback({"step": "embedding", "progress": min(95, progress), "message": f"Processing batch {i//batch_size + 1}/{(len(chunked_docs) + batch_size - 1)//batch_size}..."})
                
                # Update repository index
                self.repositories[collection_name] = {
                    "repo_url": repo_url,
                    "repo_name": repo_name,
                    "document_count": len(documents),
                    "chunk_count": len(chunked_docs),
                    "indexed_at": datetime.now().isoformat()
                }
                
                self._save_repository_index()
                
                if progress_callback:
                    progress_callback({"step": "complete", "progress": 100, "message": f"Successfully indexed {repo_name}!"})
                
                return {
                    "success": True,
                    "message": f"Successfully indexed repository {repo_name}",
                    "collection_name": collection_name,
                    "repo_name": repo_name,
                    "document_count": len(documents),
                    "chunk_count": len(chunked_docs)
                }
                
        except Exception as e:
            logger.error(f"Error indexing repository: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def query_repository(self, collection_name: str, question: str, max_results: int = 5) -> Dict[str, Any]:
        """Query an indexed repository."""
        from langchain_chroma import Chroma
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.runnables import RunnablePassthrough
        from langchain_core.output_parsers import StrOutputParser
        
        if collection_name not in self.repositories:
            return {
                "success": False,
                "error": f"Repository collection '{collection_name}' not found"
            }
        
        try:
            # Load vector store
            vector_store = Chroma(
                persist_directory=self.persist_directory,
                embedding_function=self.embeddings,
                collection_name=collection_name
            )
            
            # Set up retriever
            retriever = vector_store.as_retriever(
                search_type="similarity",
                search_kwargs={"k": max_results}
            )
            
            # Get relevant documents
            relevant_docs = retriever.get_relevant_documents(question)
            
            # Create prompt with citations
            prompt_template = """You are an expert code analyst. Use the following code snippets from the repository to answer the question.
            Provide a comprehensive answer and include specific citations with file paths and relevant code snippets.

Question: {question}

Code Context:
{context}

Instructions:
1. Answer the question based on the provided code context
2. Include specific file references in your answer
3. Quote relevant code snippets when helpful
4. If the answer isn't in the provided context, say so clearly

Answer:"""

            prompt = ChatPromptTemplate.from_template(prompt_template)
            
            def format_docs_with_citations(docs):
                formatted = []
                for i, doc in enumerate(docs, 1):
                    file_path = doc.metadata.get('file_path', 'unknown')
                    content = doc.page_content
                    formatted.append(f"[Source {i}: {file_path}]\n{content}")
                return "\n\n".join(formatted)
            
            # Create RAG chain
            rag_chain = (
                {"context": retriever | format_docs_with_citations, "question": RunnablePassthrough()}
                | prompt
                | self.llm
                | StrOutputParser()
            )
            
            # Get answer
            answer = rag_chain.invoke(question)
            
            # Prepare citations
            citations = []
            for i, doc in enumerate(relevant_docs, 1):
                citations.append({
                    "source_id": i,
                    "file_path": doc.metadata.get('file_path', 'unknown'),
                    "snippet": doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content
                })
            
            repo_info = self.repositories[collection_name]
            
            return {
                "success": True,
                "answer": answer,
                "question": question,
                "repository": repo_info["repo_name"],
                "citations": citations,
                "total_sources": len(relevant_docs)
            }
            
        except Exception as e:
            logger.error(f"Error querying repository: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def list_repositories(self) -> List[Dict[str, Any]]:
        """List all indexed repositories."""
        return [
            {
                "collection_name": collection_name,
                "repo_name": info["repo_name"],
                "repo_url": info["repo_url"],
                "document_count": info["document_count"],
                "chunk_count": info["chunk_count"]
            }
            for collection_name, info in self.repositories.items()
        ]
    
    def get_repository_memory_context(self) -> str:
        """Get memory context about indexed repositories."""
        if not self.repositories:
            return "No GitHub repositories have been indexed for RAG queries."
        
        context_parts = ["Available GitHub repositories indexed for RAG queries:"]
        for collection_name, info in self.repositories.items():
            context_parts.append(f"- {info['repo_name']} ({info['repo_url']}) - {info['document_count']} files indexed")
        
        context_parts.append("\nYou can query these repositories using the github_rag_query tool.")
        return "\n".join(context_parts)
    
    def get_repository_stats(self, repo_path: str, ignore_dirs: List[str] = None) -> Dict[str, Any]:
        """Get statistics about a repository to help with filtering decisions."""
        if ignore_dirs is None:
            ignore_dirs = ['.git', 'node_modules', '__pycache__', '.idea', '.vscode', 'venv', '.env', 'target', 'build', 'dist']
        
        stats = {
            'total_files': 0,
            'large_files': 0,
            'file_extensions': {},
            'directory_sizes': {},
            'total_size': 0
        }
        
        for root, dirs, files in os.walk(repo_path):
            # Skip ignored directories
            dirs[:] = [d for d in dirs if not any(ignore in root for ignore in ignore_dirs)]
            
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    file_size = os.path.getsize(file_path)
                    stats['total_files'] += 1
                    stats['total_size'] += file_size
                    
                    if file_size > 100000:  # Files larger than 100KB
                        stats['large_files'] += 1
                    
                    ext = os.path.splitext(file)[1].lower()
                    if ext:
                        stats['file_extensions'][ext] = stats['file_extensions'].get(ext, 0) + 1
                    
                except OSError:
                    continue
        
        return stats