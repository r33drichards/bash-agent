import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Message } from '../Message'
import type { MessageData } from '../../types'

const mockMessage: MessageData = {
  type: 'user',
  content: 'Hello, this is a test message',
  timestamp: '2023-01-01T12:00:00Z',
}

describe('Message', () => {
  it('renders user message correctly', () => {
    render(<Message message={mockMessage} />)

    expect(screen.getByText('You')).toBeInTheDocument()
    expect(screen.getByText('Hello, this is a test message')).toBeInTheDocument()
  })

  it('renders agent message with markdown', () => {
    const agentMessage: MessageData = {
      type: 'agent',
      content: '**Bold text** and `code`',
      timestamp: '2023-01-01T12:00:00Z',
    }

    render(<Message message={agentMessage} />)

    expect(screen.getByText('Agent')).toBeInTheDocument()
    expect(screen.getByText('Bold text')).toBeInTheDocument()
    expect(screen.getByText('code')).toBeInTheDocument()
  })

  it('shows streaming cursor when streaming', () => {
    render(<Message message={mockMessage} isStreaming={true} />)

    const streamingCursor = document.querySelector('.streaming-cursor')
    expect(streamingCursor).toBeInTheDocument()
  })
})
