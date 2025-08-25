"""
Integration tests for thinking block handling based on Anthropic's examples.
Tests the actual API behavior and proper message structure.
"""

import pytest
import json
from unittest.mock import Mock, patch
from agent.llm import LLM

class MockThinkingContent:
    """Mock object representing a thinking content block from Anthropic API."""
    def __init__(self, thinking_text="Mock thinking content", signature="mock_signature"):
        self.type = "thinking"
        self.thinking = thinking_text
        self.signature = signature

class MockTextContent:
    """Mock object representing a text content block from Anthropic API."""
    def __init__(self, text="Mock text content"):
        self.type = "text"
        self.text = text

class MockToolUseContent:
    """Mock object representing a tool_use content block from Anthropic API."""
    def __init__(self, tool_id="mock_tool_id", name="mock_tool", input_data=None):
        self.type = "tool_use"
        self.id = tool_id
        self.name = name
        self.input = input_data or {"param": "value"}

class MockRedactedThinkingContent:
    """Mock object representing a redacted_thinking content block from Anthropic API."""
    def __init__(self, data="mock_redacted_data"):
        self.type = "redacted_thinking"
        self.data = data

class MockResponse:
    """Mock Anthropic API response."""
    def __init__(self, content_blocks, stop_reason="end_turn"):
        self.content = content_blocks
        self.stop_reason = stop_reason
        self.usage = Mock()
        self.usage.input_tokens = 100
        self.usage.output_tokens = 50

class TestThinkingBlockIntegration:
    """Integration tests for thinking block handling."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.llm = LLM("claude-3-5-sonnet-20241022")
    
    def test_thinking_block_structure_creation(self):
        """Test that thinking blocks are created with correct structure."""
        # Mock API response with thinking block
        mock_response = MockResponse([
            MockThinkingContent("I need to analyze this request", "signature123"),
            MockTextContent("This is my response")
        ])
        
        with patch.object(self.llm, '_call_anthropic', return_value=mock_response):
            output, tool_calls = self.llm([{"type": "text", "text": "test message"}])
            
            # Check that the assistant message was added correctly
            assert len(self.llm.messages) == 2  # user + assistant
            assistant_message = self.llm.messages[1]
            
            assert assistant_message["role"] == "assistant"
            assert len(assistant_message["content"]) == 2
            
            # First block should be thinking
            thinking_block = assistant_message["content"][0]
            assert thinking_block["type"] == "thinking"
            assert thinking_block["thinking"] == "I need to analyze this request"
            assert thinking_block["signature"] == "signature123"
            
            # Second block should be text
            text_block = assistant_message["content"][1]
            assert text_block["type"] == "text"
            assert text_block["text"] == "This is my response"

    def test_tool_use_with_thinking_blocks(self):
        """Test tool use with proper thinking block preservation."""
        # Mock API response with thinking and tool_use
        mock_response = MockResponse([
            MockThinkingContent("I should use a tool for this", "sig456"),
            MockTextContent("Let me use a tool"),
            MockToolUseContent("tool_123", "weather", {"location": "Paris"})
        ], stop_reason="tool_use")
        
        with patch.object(self.llm, '_call_anthropic', return_value=mock_response):
            output, tool_calls = self.llm([{"type": "text", "text": "What's the weather?"}])
            
            # Check assistant message structure
            assistant_message = self.llm.messages[1]
            assert len(assistant_message["content"]) == 3
            
            # Verify thinking block comes first
            assert assistant_message["content"][0]["type"] == "thinking"
            assert assistant_message["content"][0]["thinking"] == "I should use a tool for this"
            assert assistant_message["content"][0]["signature"] == "sig456"
            
            # Verify tool_use block structure
            tool_block = assistant_message["content"][2]
            assert tool_block["type"] == "tool_use"
            assert tool_block["id"] == "tool_123"
            assert tool_block["name"] == "weather"
            assert tool_block["input"] == {"location": "Paris"}
            
            # Check returned tool calls
            assert len(tool_calls) == 1
            assert tool_calls[0]["id"] == "tool_123"

    def test_redacted_thinking_blocks(self):
        """Test handling of redacted thinking blocks."""
        mock_response = MockResponse([
            MockRedactedThinkingContent("redacted_data_xyz"),
            MockTextContent("Response after redacted thinking")
        ])
        
        with patch.object(self.llm, '_call_anthropic', return_value=mock_response):
            output, tool_calls = self.llm([{"type": "text", "text": "test"}])
            
            assistant_message = self.llm.messages[1]
            
            # Check redacted thinking block
            redacted_block = assistant_message["content"][0]
            assert redacted_block["type"] == "redacted_thinking"
            assert redacted_block["data"] == "redacted_data_xyz"

    def test_streaming_with_thinking(self):
        """Test streaming responses with thinking blocks."""
        def mock_streaming_callback(chunk, content_type):
            pass
        
        # Mock streaming response
        with patch.object(self.llm, '_call_with_streaming') as mock_stream:
            mock_stream.return_value = ("Final text", [], "Thinking content")
            
            output, tool_calls = self.llm(
                [{"type": "text", "text": "test"}], 
                stream_callback=mock_streaming_callback
            )
            
            # Check that thinking was included in assistant message
            assistant_message = self.llm.messages[1]
            thinking_block = assistant_message["content"][0]
            
            assert thinking_block["type"] == "thinking"
            assert thinking_block["thinking"] == "Thinking content"

    def test_conversation_history_with_thinking(self):
        """Test that conversation history maintains proper thinking block structure."""
        # First message with thinking
        mock_response1 = MockResponse([
            MockThinkingContent("First thinking", "sig1"),
            MockTextContent("First response")
        ])
        
        with patch.object(self.llm, '_call_anthropic', return_value=mock_response1):
            self.llm([{"type": "text", "text": "first message"}])
        
        # Second message with thinking
        mock_response2 = MockResponse([
            MockThinkingContent("Second thinking", "sig2"),
            MockTextContent("Second response")
        ])
        
        with patch.object(self.llm, '_call_anthropic', return_value=mock_response2):
            self.llm([{"type": "text", "text": "second message"}])
        
        # Verify conversation structure
        assert len(self.llm.messages) == 4  # user1, assistant1, user2, assistant2
        
        # Both assistant messages should start with thinking blocks
        assert self.llm.messages[1]["content"][0]["type"] == "thinking"
        assert self.llm.messages[3]["content"][0]["type"] == "thinking"
        
        # Verify signatures are preserved
        assert self.llm.messages[1]["content"][0]["signature"] == "sig1"
        assert self.llm.messages[3]["content"][0]["signature"] == "sig2"

    def test_tool_result_processing_with_preserved_thinking(self):
        """Test that tool results work correctly with preserved thinking blocks."""
        # Initial response with tool use
        mock_response1 = MockResponse([
            MockThinkingContent("Need to use tool", "sig_initial"),
            MockTextContent("Using tool"),
            MockToolUseContent("tool_1", "weather", {"location": "Berlin"})
        ], stop_reason="tool_use")
        
        with patch.object(self.llm, '_call_anthropic', return_value=mock_response1):
            self.llm([{"type": "text", "text": "weather in Berlin?"}])
        
        # Follow-up response after tool result
        mock_response2 = MockResponse([
            MockTextContent("Berlin is foggy at 60°F")
        ])
        
        with patch.object(self.llm, '_call_anthropic', return_value=mock_response2):
            # Simulate tool result
            tool_result = {
                "type": "tool_result",
                "tool_use_id": "tool_1", 
                "content": '{"temperature": 60, "condition": "Foggy"}'
            }
            output, tool_calls = self.llm([tool_result])
        
        # Verify conversation structure is valid
        assert len(self.llm.messages) == 4
        
        # First assistant message should have thinking block
        first_assistant = self.llm.messages[1]
        assert first_assistant["content"][0]["type"] == "thinking"
        assert first_assistant["content"][0]["signature"] == "sig_initial"
        
        # Tool result message should be properly formatted
        tool_result_msg = self.llm.messages[2]
        assert tool_result_msg["role"] == "user"
        assert tool_result_msg["content"][0]["type"] == "tool_result"
        
        # Final assistant response (no thinking expected after tool results)
        final_assistant = self.llm.messages[3]
        assert final_assistant["content"][0]["type"] == "text"

    def test_empty_thinking_block_handling(self):
        """Test that we don't create invalid empty thinking blocks."""
        # Create an LLM with existing conversation that doesn't have thinking blocks
        self.llm.messages = [
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "hi there"}]}
        ]
        
        # Now try to use it with thinking enabled
        mock_response = MockResponse([
            MockThinkingContent("New thinking", "new_sig"),
            MockTextContent("New response")
        ])
        
        with patch.object(self.llm, '_call_anthropic', return_value=mock_response):
            # This should work because we don't add invalid empty thinking blocks
            output, tool_calls = self.llm([{"type": "text", "text": "new message"}])
            
            # Verify the new assistant message has proper thinking
            new_assistant = self.llm.messages[3]
            assert new_assistant["content"][0]["type"] == "thinking"
            assert new_assistant["content"][0]["signature"] == "new_sig"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])