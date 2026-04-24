import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import * as api from '../../lib/api'
import { AnalystPanel } from '../analyst-panel'

describe('AnalystPanel', () => {
  afterEach(() => vi.restoreAllMocks())

  it('shows starter chips when input is empty', () => {
    render(<AnalystPanel />)
    expect(screen.getByText('Explain this pick in plain English')).toBeInTheDocument()
  })

  it('clicking a starter chip fills the input', async () => {
    const user = userEvent.setup()
    render(<AnalystPanel />)

    await user.click(screen.getByText('Why over instead of under?'))
    const input = screen.getByRole('textbox', { name: /analyst question/i })
    expect(input).toHaveValue('Why over instead of under?')
  })

  it('hides starter chips once input has text', async () => {
    const user = userEvent.setup()
    render(<AnalystPanel />)

    await user.type(screen.getByRole('textbox', { name: /analyst question/i }), 'custom')
    expect(screen.queryByText('Explain this pick in plain English')).not.toBeInTheDocument()
  })

  it('renders streamed tokens', async () => {
    const streamSpy = vi.spyOn(api, 'streamAnalyst').mockImplementation(
      async (_q, _ctx, onToken) => {
        onToken('Hello ')
        onToken('world')
      },
    )
    const user = userEvent.setup()
    render(<AnalystPanel />)

    await user.type(screen.getByRole('textbox', { name: /analyst question/i }), 'test')
    await user.click(screen.getByRole('button', { name: /send question/i }))

    await waitFor(() => expect(screen.getByText(/Hello world/)).toBeInTheDocument())
    expect(streamSpy).toHaveBeenCalledOnce()
  })

  it('renders tool_call chips', async () => {
    vi.spyOn(api, 'streamAnalyst').mockImplementation(
      async (_q, _ctx, _onToken, onToolCall) => {
        onToolCall({ name: 'get_player_stats', args: '{}' })
      },
    )
    const user = userEvent.setup()
    render(<AnalystPanel />)

    await user.type(screen.getByRole('textbox', { name: /analyst question/i }), 'test')
    await user.click(screen.getByRole('button', { name: /send question/i }))

    await waitFor(() =>
      expect(screen.getByText(/Tool call: get_player_stats/)).toBeInTheDocument(),
    )
  })

  it('abort button stops the stream', async () => {
    let resolveStream: () => void
    vi.spyOn(api, 'streamAnalyst').mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveStream = resolve
        }),
    )
    const user = userEvent.setup()
    render(<AnalystPanel />)

    await user.type(screen.getByRole('textbox', { name: /analyst question/i }), 'test')
    await user.click(screen.getByRole('button', { name: /send question/i }))

    await waitFor(() => screen.getByRole('button', { name: /stop streaming/i }))
    await user.click(screen.getByRole('button', { name: /stop streaming/i }))

    resolveStream!()
    await waitFor(() => screen.getByRole('button', { name: /send question/i }))
  })
})
