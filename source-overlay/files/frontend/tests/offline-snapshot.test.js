import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import OfflineSnapshotBar from '~/components/chat/OfflineSnapshotBar.vue'
import { defineComponent, h, ref } from 'vue'
import { useChatMessages } from '~/composables/chat/useChatMessages'
vi.mock('~/lib/server-error-logging', () => ({ reportServerError: vi.fn() }))
vi.mock('~/stores/chatAccounts', () => ({ useChatAccountsStore: () => ({ applySourceResponse: vi.fn() }) }))

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe('local snapshot updates', () => {
  it('handles an SSE update immediately and closes the old stream when switching accounts', async () => {
    const streams = []
    vi.stubGlobal('EventSource', class {
      constructor(url) { this.url = url; this.close = vi.fn(); streams.push(this) }
    })
    vi.stubGlobal('$fetch', vi.fn(async () => ({ available: true, version: 0, revision: 0, instance: 'one' })))
    const wrapper = mount(OfflineSnapshotBar, { props: { account: 'first' } })
    await flushPromises()
    expect(wrapper.text()).toBe('')
    expect(wrapper.find('button').exists()).toBe(false)
    streams[0].onmessage({ data: JSON.stringify({ available: true, version: 1, revision: 2, instance: 'one' }) })
    await flushPromises()
    expect(wrapper.emitted('updated')).toHaveLength(1)
    await wrapper.setProps({ account: 'second' })
    expect(streams[0].close).toHaveBeenCalled()
    streams[0].onmessage({ data: JSON.stringify({ version: 9 }) })
    await flushPromises()
    expect(wrapper.emitted('updated')).toHaveLength(1)
    wrapper.unmount()
    expect(streams[1].close).toHaveBeenCalled()
  })

  it('merges local messages with realtime native mode disabled and preserves history', async () => {
    const api = { listChatMessages: vi.fn(async () => ({ messages: [
      { id: 'new', localId: 2, createTime: 2000000001, localType: 1, content: 'synthetic-new' }
    ] })) }
    let state
    const wrapper = mount(defineComponent({ setup() {
      state = useChatMessages({ api, apiBase: '/api', selectedAccount: ref('synthetic'),
        selectedContact: ref({ username: 'synthetic-friend' }), realtimeEnabled: ref(false),
        privacyMode: ref(false), searchContext: ref({ active: false }) })
      return () => h('div')
    } }))
    state.allMessages.value = { 'synthetic-friend': [{ id: 'old', content: 'synthetic-history' }] }
    await state.refreshOfflineMessages()
    expect(api.listChatMessages).toHaveBeenCalledWith(expect.objectContaining({ source: 'decrypted' }))
    expect(state.allMessages.value['synthetic-friend'].map(item => item.id)).toContain('old')
    expect(state.allMessages.value['synthetic-friend']).toHaveLength(2)
    wrapper.unmount()
  })
  it('keeps fallback updates active without rendering a status bar or requesting refresh jobs', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', undefined)
    let version = 0
    const fetch = vi.fn(async () => ({ available: true, running: false, version, errors: [], checked_at: 2000000000 }))
    vi.stubGlobal('$fetch', fetch)
    const wrapper = mount(OfflineSnapshotBar, { props: { account: 'synthetic-account' } })
    await flushPromises()
    expect(wrapper.text()).toBe('')
    version = 1
    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()
    expect(wrapper.emitted('updated')).toHaveLength(1)
    expect(fetch.mock.calls.every(([url]) => url === '/api/offline/snapshot/status')).toBe(true)
    wrapper.unmount()
  })

  it('ignores an old account response after switching accounts', async () => {
    let complete
    vi.stubGlobal('$fetch', vi.fn((_url, options) => options.query.account === 'old'
      ? new Promise(resolve => { complete = resolve })
      : Promise.resolve({ available: true, version: 0, errors: [] })))
    const wrapper = mount(OfflineSnapshotBar, { props: { account: 'old' } })
    await wrapper.setProps({ account: 'new' })
    await flushPromises()
    complete({ available: false, version: 9 })
    await flushPromises()
    expect(wrapper.find('button').exists()).toBe(false)
    expect(wrapper.emitted('updated')).toBeUndefined()
    wrapper.unmount()
  })
})
