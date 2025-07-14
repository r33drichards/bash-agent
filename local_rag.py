#!/usr/bin/env python3
"""
Local RAG Support - Helper functions for agent.py to handle local file paths in RAG
"""

def github_rag_index_local(dir_path, collection_name=None, include_extensions=None, ignore_dirs=None):
    """Index a local directory for RAG queries."""
    from memory import save_memory
    from agent import get_current_github_rag
    
    try:
        github_rag = get_current_github_rag()
        result = github_rag.index_local_directory(
            dir_path=dir_path,
            collection_name=collection_name,
            include_extensions=include_extensions,
            ignore_dirs=ignore_dirs
        )
        
        if result["success"]:
            save_memory(
                title=f"Local Directory RAG Index: {result['dir_name']}",
                content=f"Local directory at {dir_path} indexed for RAG queries. Collection name: {result['collection_name']}. Contains {result['document_count']} files.",
                tags=['github_rag', 'local_directory', result['dir_name']]
            )
            return f"✅ {result['message']}\n\nDirectory: {result['dir_name']}\nCollection: {result['collection_name']}\nDocuments indexed: {result.get('document_count', 0)}\nChunks created: {result.get('chunk_count', 0)}\n\nYou can now query this directory using the github_rag_query tool with collection_name: {result['collection_name']}"
        else:
            return f"❌ Error: {result['error']}"
    except Exception as e:
        return f"❌ Error indexing local directory: {str(e)}"