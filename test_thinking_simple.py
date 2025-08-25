#!/usr/bin/env python3
"""
Simple test for thinking block functionality without pytest
"""

import json
import sys
import os
from unittest.mock import Mock, patch

# Add the current directory to the path so we can import agent modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_thinking_block_structure():
    """Test that thinking blocks are created with correct structure"""
    print("Testing thinking block structure...")
    
    with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
        with patch('agent.llm.anthropic.Anthropic') as mock_anthropic:
            # Import here to ensure patches are in place
            from agent.llm import LLM
            
            # Mock client
            mock_client = Mock()
            mock_anthropic.return_value = mock_client
            
            # Create LLM instance
            llm = LLM("claude-3-sonnet-20240229")
            llm.client = mock_client
            
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
            
            mock_client.messages.create.return_value = mock_response
            
            # Call the LLM
            output, tool_calls = llm([{"type": "text", "text": "test message"}])
            
            # Check that messages were built correctly
            assert len(llm.messages) == 2, f"Expected 2 messages, got {len(llm.messages)}"
            
            assistant_message = llm.messages[1]
            assert assistant_message["role"] == "assistant"
            assert len(assistant_message["content"]) == 2
            
            # Check thinking block structure
            thinking_block = assistant_message["content"][0]
            print(f"Thinking block structure: {thinking_block}")
            
            assert thinking_block["type"] == "thinking", f"Expected type 'thinking', got {thinking_block.get('type')}"
            assert thinking_block["thinking"] == "I need to search for information about this topic."
            assert "text" not in thinking_block, "Should not have text field in thinking block"
            
            # Check that it serializes correctly
            try:
                json_str = json.dumps(thinking_block)
                print(f"Thinking block JSON: {json_str}")
            except Exception as e:
                raise AssertionError(f"Thinking block cannot be JSON serialized: {str(e)}")
            
            print("✓ Thinking block structure test passed")

def test_message_history_with_thinking():
    """Test that thinking blocks in message history don't get corrupted"""
    print("Testing message history with thinking blocks...")
    
    with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
        with patch('agent.llm.anthropic.Anthropic') as mock_anthropic:
            from agent.llm import LLM
            
            mock_client = Mock()
            mock_anthropic.return_value = mock_client
            llm = LLM("claude-3-sonnet-20240229")
            llm.client = mock_client
            
            # Manually add a message with thinking block (simulating a previous conversation)
            llm.messages = [
                {"role": "user", "content": [{"type": "text", "text": "first message"}]},
                {
                    "role": "assistant", 
                    "content": [
                        {"type": "thinking", "thinking": "Let me think about this..."},
                        {"type": "text", "text": "Here's my response."}
                    ]
                }
            ]
            
            print("Before follow-up call:")
            print(f"Assistant message structure: {llm.messages[1]['content']}")
            
            # Mock a follow-up API response
            mock_response = Mock()
            mock_response.content = []
            mock_response.usage.input_tokens = 50
            mock_response.usage.output_tokens = 100
            
            mock_client.messages.create.return_value = mock_response
            
            # Make another call - this should use the existing message history
            try:
                output, tool_calls = llm([{"type": "text", "text": "follow up"}])
                
                # Verify the API was called with correct structure
                call_args = mock_client.messages.create.call_args
                messages_sent = call_args[1]['messages']  # keyword arguments
                
                print("Messages sent to API:")
                for i, msg in enumerate(messages_sent):
                    print(f"  Message {i}: role={msg['role']}")
                    if 'content' in msg:
                        for j, content in enumerate(msg['content']):
                            print(f"    Content {j}: {content}")
                
                # Check the assistant message structure
                assistant_msg = messages_sent[1]
                thinking_block = assistant_msg['content'][0]
                
                print(f"Thinking block sent to API: {thinking_block}")
                
                # This should have correct thinking structure
                assert thinking_block['type'] == 'thinking'
                assert 'thinking' in thinking_block
                assert thinking_block['thinking'] == "Let me think about this..."
                
                # Should not have text field in thinking block
                assert 'text' not in thinking_block
                
                print("✓ Message history test passed")
                
            except Exception as e:
                print(f"✗ API call failed with thinking blocks in message history: {str(e)}")
                print(f"Messages structure when error occurred:")
                for i, msg in enumerate(llm.messages):
                    print(f"  Message {i}: {msg}")
                raise

def test_message_validation():
    """Test that message validation preserves thinking blocks"""
    print("Testing message validation...")
    
    with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
        with patch('agent.llm.anthropic.Anthropic') as mock_anthropic:
            from agent.llm import LLM
            
            mock_client = Mock()
            mock_anthropic.return_value = mock_client
            llm = LLM("claude-3-sonnet-20240229")
            
            # Create a message with thinking block
            original_thinking_block = {"type": "thinking", "thinking": "Original thinking content"}
            original_text_block = {"type": "text", "text": "Original response"}
            
            llm.messages = [
                {"role": "user", "content": [{"type": "text", "text": "test"}]},
                {
                    "role": "assistant",
                    "content": [original_thinking_block.copy(), original_text_block.copy()]
                }
            ]
            
            print("Before validation:")
            print(f"Thinking block: {llm.messages[1]['content'][0]}")
            
            # Run message validation
            llm._validate_message_structure(skip_active_tools=False)
            
            print("After validation:")
            print(f"Thinking block: {llm.messages[1]['content'][0]}")
            
            # Check that thinking block structure is preserved
            assistant_message = llm.messages[1]
            thinking_block = assistant_message["content"][0]
            
            assert thinking_block["type"] == "thinking"
            assert thinking_block["thinking"] == "Original thinking content"
            
            # Should not have text field in thinking block
            assert "text" not in thinking_block
            
            # Verify it would serialize correctly for JSON
            try:
                json.dumps(assistant_message["content"][0])
                print("✓ Message validation test passed")
            except Exception as e:
                raise AssertionError(f"Thinking block cannot be JSON serialized after validation: {str(e)}")

def main():
    """Run all tests"""
    print("Running thinking block tests...")
    print("=" * 50)
    
    try:
        test_thinking_block_structure()
        print()
        test_message_history_with_thinking()
        print()
        test_message_validation()
        print()
        print("=" * 50)
        print("All tests passed! ✓")
        return 0
    except Exception as e:
        print(f"Test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())