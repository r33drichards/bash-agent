import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from agent.llm import LLM


class TestThinkingBlocks:
    """Test thinking block functionality in LLM class"""

    @pytest.fixture
    def mock_anthropic_client(self):
        """Mock Anthropic client"""
        with patch('agent.llm.anthropic.Anthropic') as mock_anthropic:
            mock_client = Mock()
            mock_anthropic.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def llm_instance(self, mock_anthropic_client):
        """Create LLM instance with mocked client"""
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            llm = LLM("claude-3-sonnet-20240229")
            llm.client = mock_anthropic_client
            return llm

    def test_thinking_block_structure_creation(self, llm_instance):
        """Test that thinking blocks are created with correct structure"""
        
        # Mock the API response with thinking content
        mock_thinking_content = Mock()
        mock_thinking_content.type = "thinking"
        mock_thinking_content.thinking = "I need to search for information about this topic."
        mock_thinking_content.signature = "fake_signature_123"  # Use string instead of Mock for JSON serialization
        
        mock_text_content = Mock()
        mock_text_content.type = "text"
        mock_text_content.text = "Here's what I found."
        
        mock_response = Mock()
        mock_response.content = [mock_thinking_content, mock_text_content]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 200
        
        llm_instance.client.messages.create.return_value = mock_response
        
        # Call the LLM
        output, tool_calls = llm_instance([{"type": "text", "text": "test message"}])
        
        # Check that messages were built correctly
        assert len(llm_instance.messages) == 2  # user + assistant
        
        assistant_message = llm_instance.messages[1]
        assert assistant_message["role"] == "assistant"
        assert len(assistant_message["content"]) == 2
        
        # Check thinking block structure
        thinking_block = assistant_message["content"][0]
        assert thinking_block["type"] == "thinking"
        assert thinking_block["thinking"] == "I need to search for information about this topic."
        assert "text" not in thinking_block  # Should not have text field in thinking block
        
        # Check text block structure
        text_block = assistant_message["content"][1]
        assert text_block["type"] == "text"
        assert text_block["text"] == "Here's what I found."

    def test_thinking_block_serialization(self, llm_instance):
        """Test that thinking blocks serialize correctly for API calls"""
        
        # Add a message with thinking block manually
        llm_instance.messages = [
            {"role": "user", "content": [{"type": "text", "text": "first message"}]},
            {
                "role": "assistant", 
                "content": [
                    {"type": "thinking", "thinking": "Let me think about this..."},
                    {"type": "text", "text": "Here's my response."}
                ]
            }
        ]
        
        # Mock a follow-up API response
        mock_response = Mock()
        mock_response.content = []
        mock_response.usage.input_tokens = 50
        mock_response.usage.output_tokens = 100
        
        llm_instance.client.messages.create.return_value = mock_response
        
        # Make another call - this should use the existing message history
        try:
            output, tool_calls = llm_instance([{"type": "text", "text": "follow up"}])
            
            # Verify the API was called with correct structure
            call_args = llm_instance.client.messages.create.call_args
            messages_sent = call_args[1]['messages']  # keyword arguments
            
            # Check the assistant message structure
            assistant_msg = messages_sent[1]
            thinking_block = assistant_msg['content'][0]
            
            # This should have correct thinking structure
            assert thinking_block['type'] == 'thinking'
            assert 'thinking' in thinking_block
            assert thinking_block['thinking'] == "Let me think about this..."
            
            # Should not have text field in thinking block
            assert 'text' not in thinking_block
            
        except Exception as e:
            pytest.fail(f"API call failed with thinking blocks in message history: {str(e)}")

    def test_no_placeholder_thinking_blocks(self, llm_instance):
        """Test that we don't add placeholder thinking blocks"""
        
        # Mock API response without thinking content
        mock_text_content = Mock()
        mock_text_content.type = "text"
        mock_text_content.text = "Response without thinking."
        
        mock_response = Mock()
        mock_response.content = [mock_text_content]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 150
        
        llm_instance.client.messages.create.return_value = mock_response
        
        # Call the LLM
        output, tool_calls = llm_instance([{"type": "text", "text": "test message"}])
        
        # Check that no placeholder thinking blocks were added
        assistant_message = llm_instance.messages[1]
        content_types = [block["type"] for block in assistant_message["content"]]
        
        # Should only have text content, no thinking
        assert content_types == ["text"]
        assert assistant_message["content"][0]["text"] == "Response without thinking."

    def test_streaming_thinking_blocks(self, llm_instance):
        """Test thinking blocks in streaming mode"""
        
        # Mock streaming response
        def mock_stream_generator():
            # Message start
            mock_start = Mock()
            mock_start.type = "message_start"
            mock_start.message.usage.input_tokens = 100
            yield mock_start
            
            # Thinking content block start
            mock_thinking_start = Mock()
            mock_thinking_start.type = "content_block_start"
            mock_thinking_start.content_block.type = "thinking"
            yield mock_thinking_start
            
            # Thinking content delta
            mock_thinking_delta = Mock()
            mock_thinking_delta.type = "content_block_delta"
            mock_thinking_delta.delta.type = "text_delta"
            mock_thinking_delta.delta.text = "Let me think... "
            yield mock_thinking_delta
            
            # More thinking content
            mock_thinking_delta2 = Mock()
            mock_thinking_delta2.type = "content_block_delta"
            mock_thinking_delta2.delta.type = "text_delta"
            mock_thinking_delta2.delta.text = "this is complex."
            yield mock_thinking_delta2
            
            # Text content block start
            mock_text_start = Mock()
            mock_text_start.type = "content_block_start"
            mock_text_start.content_block.type = "text"
            yield mock_text_start
            
            # Text content delta
            mock_text_delta = Mock()
            mock_text_delta.type = "content_block_delta"
            mock_text_delta.delta.type = "text_delta"
            mock_text_delta.delta.text = "Here's my response."
            yield mock_text_delta
            
            # Message stop
            mock_stop = Mock()
            mock_stop.type = "message_stop"
            mock_stop.usage.output_tokens = 200
            yield mock_stop
        
        # Mock the streaming context manager
        mock_stream_context = MagicMock()
        mock_stream_context.__enter__.return_value = mock_stream_generator()
        mock_stream_context.__exit__.return_value = None
        
        llm_instance.client.messages.create.return_value = mock_stream_context
        
        # Mock streaming callback
        stream_callback = Mock()
        
        # Call with streaming
        output, tool_calls = llm_instance([{"type": "text", "text": "test"}], stream_callback=stream_callback)
        
        # Verify streaming callback was called for thinking content
        thinking_calls = [call for call in stream_callback.call_args_list if call[0][1] == "thinking"]
        content_calls = [call for call in stream_callback.call_args_list if call[0][1] == "content"]
        
        assert len(thinking_calls) == 2  # Two thinking chunks
        assert thinking_calls[0][0][0] == "Let me think... "
        assert thinking_calls[1][0][0] == "this is complex."
        
        assert len(content_calls) == 1  # One content chunk
        assert content_calls[0][0][0] == "Here's my response."
        
        # Check message structure
        assistant_message = llm_instance.messages[1]
        assert len(assistant_message["content"]) == 2
        
        thinking_block = assistant_message["content"][0]
        assert thinking_block["type"] == "thinking"
        # In streaming mode, the thinking text gets concatenated from chunks
        assert thinking_block["thinking"] == "Let me think... this is complex."
        
        text_block = assistant_message["content"][1]
        assert text_block["type"] == "text"
        assert text_block["text"] == "Here's my response."

    def test_message_validation_preserves_thinking_blocks(self, llm_instance):
        """Test that message validation doesn't corrupt thinking blocks"""
        
        # Create a message with thinking block
        original_thinking_block = {"type": "thinking", "thinking": "Original thinking content"}
        original_text_block = {"type": "text", "text": "Original response"}
        
        llm_instance.messages = [
            {"role": "user", "content": [{"type": "text", "text": "test"}]},
            {
                "role": "assistant",
                "content": [original_thinking_block.copy(), original_text_block.copy()]
            }
        ]
        
        # Run message validation
        llm_instance._validate_message_structure(skip_active_tools=False)
        
        # Check that thinking block structure is preserved
        assistant_message = llm_instance.messages[1]
        thinking_block = assistant_message["content"][0]
        
        assert thinking_block["type"] == "thinking"
        assert thinking_block["thinking"] == "Original thinking content"
        assert "text" not in thinking_block
        
        # Verify it would serialize correctly for JSON
        try:
            json.dumps(assistant_message["content"][0])
        except Exception as e:
            pytest.fail(f"Thinking block cannot be JSON serialized: {str(e)}")

    def test_tool_use_with_thinking_blocks(self, llm_instance):
        """Test thinking blocks work correctly with tool use"""
        
        # Mock API response with thinking + tool use
        mock_thinking = Mock()
        mock_thinking.type = "thinking"
        mock_thinking.thinking = "I need to use a tool for this."
        mock_thinking.signature = "fake_signature_456"
        
        mock_text = Mock()
        mock_text.type = "text"
        mock_text.text = "Let me search for that information."
        
        mock_tool_use = Mock()
        mock_tool_use.type = "tool_use"
        mock_tool_use.id = "tool_123"
        mock_tool_use.name = "search_tool"
        mock_tool_use.input = {"query": "test"}
        
        mock_response = Mock()
        mock_response.content = [mock_thinking, mock_text, mock_tool_use]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 200
        
        llm_instance.client.messages.create.return_value = mock_response
        
        # Call the LLM
        output, tool_calls = llm_instance([{"type": "text", "text": "search for something"}])
        
        # Verify message structure
        assistant_message = llm_instance.messages[1]
        assert len(assistant_message["content"]) == 3
        
        # Check thinking block (should be first)
        thinking_block = assistant_message["content"][0]
        assert thinking_block["type"] == "thinking"
        assert thinking_block["thinking"] == "I need to use a tool for this."
        
        # Check text block
        text_block = assistant_message["content"][1]
        assert text_block["type"] == "text"
        assert text_block["text"] == "Let me search for that information."
        
        # Check tool use block
        tool_block = assistant_message["content"][2]
        assert tool_block["type"] == "tool_use"
        assert tool_block["id"] == "tool_123"
        assert tool_block["name"] == "search_tool"
        assert tool_block["input"] == {"query": "test"}
        
        # Verify tool_calls return value
        assert len(tool_calls) == 1
        assert tool_calls[0]["id"] == "tool_123"
        assert tool_calls[0]["name"] == "search_tool"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])