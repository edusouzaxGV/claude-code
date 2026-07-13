import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock the auth/oauth boundary so fetchCodeSessionsFromSessionsAPI can run
// without a real Claude.ai login, and axios so no network is touched.
vi.mock('axios', () => {
  const get = vi.fn()
  return { default: { get }, __esModule: true }
})
vi.mock('../../src/utils/auth.js', () => ({
  getClaudeAIOAuthTokens: () => ({ accessToken: 'test-token' }),
}))
vi.mock('../../src/services/oauth/client.js', () => ({
  getOrganizationUUID: async () => 'org-uuid-1234',
}))
vi.mock('../../src/constants/oauth.js', () => ({
  getOauthConfig: () => ({ BASE_API_URL: 'https://api.example.test' }),
}))

import axios from 'axios'
import {
  fetchCodeSessionsFromSessionsAPI,
  type ListSessionsResponse,
  type SessionResource,
} from '../../src/utils/teleport/api.js'

const axiosGet = vi.mocked(axios.get)

function makeSession(id: string): SessionResource {
  return {
    type: 'session',
    id,
    title: `Session ${id}`,
    session_status: 'idle',
    environment_id: 'env-1',
    created_at: '2026-07-01T00:00:00Z',
    updated_at: '2026-07-02T00:00:00Z',
    session_context: {
      sources: [],
      cwd: '/repo',
      outcomes: null,
      custom_system_prompt: null,
      append_system_prompt: null,
      model: null,
    },
  }
}

function page(
  sessions: SessionResource[],
  hasMore: boolean,
): { status: number; statusText: string; data: ListSessionsResponse } {
  return {
    status: 200,
    statusText: 'OK',
    data: {
      data: sessions,
      has_more: hasMore,
      first_id: sessions[0]?.id ?? null,
      last_id: sessions[sessions.length - 1]?.id ?? null,
    },
  }
}

describe('fetchCodeSessionsFromSessionsAPI pagination', () => {
  beforeEach(() => {
    axiosGet.mockReset()
  })

  it('returns all sessions from a single page', async () => {
    axiosGet.mockResolvedValueOnce(page([makeSession('s1'), makeSession('s2')], false))

    const sessions = await fetchCodeSessionsFromSessionsAPI()

    expect(sessions.map(s => s.id)).toEqual(['s1', 's2'])
    expect(axiosGet).toHaveBeenCalledTimes(1)
    expect(axiosGet.mock.calls[0]?.[1]?.params).toBeUndefined()
  })

  it('follows has_more across pages using the last_id cursor', async () => {
    axiosGet
      .mockResolvedValueOnce(page([makeSession('s1'), makeSession('s2')], true))
      .mockResolvedValueOnce(page([makeSession('s3'), makeSession('s4')], true))
      .mockResolvedValueOnce(page([makeSession('s5')], false))

    const sessions = await fetchCodeSessionsFromSessionsAPI()

    expect(sessions.map(s => s.id)).toEqual(['s1', 's2', 's3', 's4', 's5'])
    expect(axiosGet).toHaveBeenCalledTimes(3)
    expect(axiosGet.mock.calls[0]?.[1]?.params).toBeUndefined()
    expect(axiosGet.mock.calls[1]?.[1]?.params).toEqual({ after_id: 's2' })
    expect(axiosGet.mock.calls[2]?.[1]?.params).toEqual({ after_id: 's4' })
  })

  it('stops when has_more is true but last_id is null (no infinite loop)', async () => {
    axiosGet.mockResolvedValueOnce({
      status: 200,
      statusText: 'OK',
      data: { data: [makeSession('s1')], has_more: true, first_id: 's1', last_id: null },
    })

    const sessions = await fetchCodeSessionsFromSessionsAPI()

    expect(sessions.map(s => s.id)).toEqual(['s1'])
    expect(axiosGet).toHaveBeenCalledTimes(1)
  })

  it('throws on a non-200 response', async () => {
    axiosGet.mockResolvedValueOnce({
      status: 500,
      statusText: 'Internal Server Error',
      data: {},
    })

    await expect(fetchCodeSessionsFromSessionsAPI()).rejects.toThrow(
      'Failed to fetch code sessions',
    )
  })
})
