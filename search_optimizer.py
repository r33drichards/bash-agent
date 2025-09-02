"""
Search Query Optimizer - Extracts relevant search terms from long prompts
"""

import re
from typing import List, Optional
import json

class SearchQueryOptimizer:
    """Intelligently extracts search terms from long prompts."""
    
    # Common words to exclude from search terms
    STOP_WORDS = {
        'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
        'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the',
        'to', 'was', 'will', 'with', 'the', 'this', 'these', 'those',
        'i', 'you', 'we', 'they', 'me', 'him', 'her', 'us', 'them',
        'what', 'when', 'where', 'who', 'why', 'how', 'which',
        'can', 'could', 'should', 'would', 'may', 'might', 'must',
        'do', 'does', 'did', 'done', 'have', 'had', 'having',
        'about', 'after', 'before', 'during', 'under', 'over'
    }
    
    # Keywords that indicate search intent
    SEARCH_INDICATORS = {
        'find', 'search', 'look for', 'locate', 'get', 'retrieve', 'fetch',
        'show', 'display', 'list', 'check', 'remember', 'recall', 'todo',
        'task', 'memory', 'note', 'saved', 'stored', 'previous', 'earlier'
    }
    
    def __init__(self):
        """Initialize the search query optimizer."""
        pass
    
    def extract_search_terms(self, prompt: str, max_terms: int = 5) -> str:
        """
        Extract relevant search terms from a long prompt.
        
        Args:
            prompt: The full prompt text
            max_terms: Maximum number of search terms to extract
            
        Returns:
            A optimized search query string
        """
        if not prompt:
            return ""
        
        # If prompt is already short, just clean it up
        if len(prompt) <= 100:
            return self._clean_query(prompt)
        
        # Strategy 1: Look for quoted strings (highest priority)
        quoted_terms = self._extract_quoted_strings(prompt)
        if quoted_terms:
            return " ".join(quoted_terms[:max_terms])
        
        # Strategy 2: Extract key phrases after search indicators
        search_phrases = self._extract_after_search_keywords(prompt)
        if search_phrases:
            return search_phrases
        
        # Strategy 3: Extract important nouns and technical terms
        key_terms = self._extract_key_terms(prompt, max_terms)
        if key_terms:
            return " ".join(key_terms)
        
        # Fallback: Return first few meaningful words
        return self._fallback_extraction(prompt, max_terms)
    
    def _extract_quoted_strings(self, text: str) -> List[str]:
        """Extract strings in quotes - these are likely important search terms."""
        # Find strings in single or double quotes
        pattern = r'["\']([^"\']+)["\']'
        matches = re.findall(pattern, text)
        # Return the quoted content as a single search phrase
        result = [match.strip() for match in matches if len(match.strip()) > 2]
        if result:
            return [' '.join(result)]  # Join all quoted strings
        return []
    
    def _extract_after_search_keywords(self, text: str) -> Optional[str]:
        """Extract text that appears after search-related keywords."""
        text_lower = text.lower()
        
        best_match = None
        best_score = 0
        
        for indicator in self.SEARCH_INDICATORS:
            if indicator in text_lower:
                # Find position of indicator
                pos = text_lower.find(indicator)
                # Extract text after the indicator
                after_text = text[pos + len(indicator):].strip()
                
                # Look for natural phrase boundaries
                # Take up to punctuation, newline, or 100 chars
                end_pos = len(after_text)
                for i, char in enumerate(after_text[:100]):
                    if char in '.!?\n,':
                        end_pos = i
                        break
                
                if end_pos == len(after_text):
                    end_pos = min(100, len(after_text))
                
                search_phrase = after_text[:end_pos].strip()
                # Remove common filler words at the start
                search_phrase = re.sub(r'^(the |a |an |for |about |with |of )+', '', search_phrase, flags=re.IGNORECASE)
                # Clean up the phrase
                search_phrase = self._clean_query(search_phrase)
                
                # Score this match (prefer longer, more specific matches)
                if len(search_phrase) > 3:
                    score = len(search_phrase) + (10 if indicator in ['find', 'search', 'look for'] else 5)
                    if score > best_score:
                        best_match = search_phrase
                        best_score = score
        
        return best_match
    
    def _extract_key_terms(self, text: str, max_terms: int) -> List[str]:
        """Extract key technical terms and important nouns."""
        # Remove special characters and split into words
        words = re.findall(r'\b[a-zA-Z0-9_]+\b', text)
        
        # Filter and score words
        word_scores = {}
        for word in words:
            word_lower = word.lower()
            
            # Skip stop words and very short words
            if word_lower in self.STOP_WORDS or len(word) < 3:
                continue
            
            # Score based on various factors
            score = 0
            
            # Capitalized words (likely proper nouns)
            if word[0].isupper() and not text.startswith(word):
                score += 2
            
            # Technical terms (contains underscore or camelCase)
            if '_' in word or (any(c.isupper() for c in word[1:])):
                score += 3
            
            # Longer words are often more specific
            if len(word) > 6:
                score += 1
            
            # Numbers mixed with letters (like error codes)
            if any(c.isdigit() for c in word) and any(c.isalpha() for c in word):
                score += 2
            
            # File extensions or technical terms
            if '.' in word or word.endswith(('.py', '.js', '.ts', '.md', '.txt')):
                score += 3
            
            # Track the best score for each word
            if word_lower not in word_scores or word_scores[word_lower]['score'] < score:
                word_scores[word_lower] = {'word': word, 'score': score}
        
        # Sort by score and return top terms
        sorted_terms = sorted(word_scores.values(), key=lambda x: x['score'], reverse=True)
        return [term['word'] for term in sorted_terms[:max_terms]]
    
    def _clean_query(self, query: str) -> str:
        """Clean up a search query."""
        # Remove excessive whitespace
        query = ' '.join(query.split())
        
        # Remove certain punctuation but keep some for technical terms
        query = re.sub(r'[,;:()[\]{}]', ' ', query)
        
        # Remove multiple spaces
        query = ' '.join(query.split())
        
        # Truncate if still too long
        if len(query) > 100:
            query = query[:100]
        
        return query.strip()
    
    def _fallback_extraction(self, text: str, max_terms: int) -> str:
        """Fallback extraction when other methods don't yield results."""
        # Take first 100 chars and extract meaningful words
        sample = text[:200]
        words = re.findall(r'\b[a-zA-Z0-9_]+\b', sample)
        
        # Filter out stop words
        meaningful_words = [
            word for word in words 
            if word.lower() not in self.STOP_WORDS and len(word) > 2
        ]
        
        return ' '.join(meaningful_words[:max_terms])
    
    def optimize_for_todo_search(self, prompt: str) -> str:
        """Optimize a prompt specifically for todo search."""
        # Look for task-related keywords
        task_keywords = ['todo', 'task', 'issue', 'bug', 'feature', 'fix', 'implement', 
                        'create', 'update', 'complete', 'in progress', 'pending']
        
        # Check if prompt mentions any task keywords
        prompt_lower = prompt.lower()
        mentioned_keywords = [kw for kw in task_keywords if kw in prompt_lower]
        
        # Extract general search terms
        general_terms = self.extract_search_terms(prompt, max_terms=3)
        
        # Combine task keywords with general terms
        if mentioned_keywords:
            return f"{' '.join(mentioned_keywords[:2])} {general_terms}"
        
        return general_terms
    
    def optimize_for_memory_search(self, prompt: str) -> str:
        """Optimize a prompt specifically for memory search."""
        # Look for memory-related keywords
        memory_keywords = ['memory', 'remember', 'note', 'saved', 'stored', 
                          'previous', 'earlier', 'last time', 'before']
        
        # Check if prompt mentions any memory keywords
        prompt_lower = prompt.lower()
        mentioned_keywords = [kw for kw in memory_keywords if kw in prompt_lower]
        
        # Extract general search terms
        general_terms = self.extract_search_terms(prompt, max_terms=3)
        
        # Combine memory keywords with general terms if relevant
        if mentioned_keywords and len(general_terms) < 20:
            return f"{mentioned_keywords[0]} {general_terms}"
        
        return general_terms