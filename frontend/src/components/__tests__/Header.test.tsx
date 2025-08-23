import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Header } from '../Header'
import type { TokenUsageData } from '../../types'

const mockTokenUsage: TokenUsageData = {
  total_tokens: 1000,
  total_input_tokens: 600,
  total_output_tokens: 400,
}

describe('Header', () => {
  it('renders correctly when connected', () => {
    render(
      <Header
        isConnected={true}
        autoConfirmEnabled={false}
        tokenUsage={mockTokenUsage}
        onToggleAutoConfirm={vi.fn()}
        onShowHistory={vi.fn()}
      />
    )

    expect(screen.getByText('Claude Code Agent')).toBeInTheDocument()
    expect(screen.getByText('Connected')).toBeInTheDocument()
    expect(screen.getByText('History')).toBeInTheDocument()
    expect(screen.getByText('Auto-confirm')).toBeInTheDocument()
  })

  it('shows disconnected status when not connected', () => {
    render(
      <Header
        isConnected={false}
        autoConfirmEnabled={false}
        tokenUsage={mockTokenUsage}
        onToggleAutoConfirm={vi.fn()}
        onShowHistory={vi.fn()}
      />
    )

    expect(screen.getByText('Disconnected')).toBeInTheDocument()
  })
})
