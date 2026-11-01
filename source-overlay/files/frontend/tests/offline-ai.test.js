import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import OfflineAiPanel from '~/components/OfflineAiPanel.vue'

vi.mock('~/stores/chatAccounts', () => ({ useChatAccountsStore: () => ({
  accounts: ['synthetic-account'], selectedAccount: 'synthetic-account', ensureLoaded: vi.fn(async () => {})
}) }))
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

function fixture() {
  const fetch = vi.fn(async (url, options = {}) => {
    if (url.endsWith('/settings')) return { enabled: false, base_url: 'http://127.0.0.1:11434/v1', model: '', key_present: false }
    if (url.endsWith('/grant')) return options.method === 'POST'
      ? { active: true, expires_at: Date.now() / 1000 + 600, characters: options.body.text.length }
      : { active: false }
    return {}
  })
  vi.stubGlobal('$fetch', fetch)
  const wrapper = mount(OfflineAiPanel)
  return { wrapper, fetch }
}
const button = (wrapper, text) => wrapper.findAll('button').find(item => item.text() === text)

describe('private AI controls', () => {
  it('does not load chat bodies or call a model on entry', async () => {
    const { wrapper, fetch } = fixture()
    await flushPromises()
    expect(fetch.mock.calls.every(([url]) => url.endsWith('/settings') || url.endsWith('/grant'))).toBe(true)
    expect(wrapper.text()).not.toContain('高级版')
    expect(wrapper.text()).not.toContain('Pro')
    expect(wrapper.find('input[type=checkbox]').element.checked).toBe(false)
    wrapper.unmount()
  })

  it('grants exactly the preview only after explicit cloud acknowledgment', async () => {
    const { wrapper, fetch } = fixture()
    await flushPromises()
    await wrapper.findAll('textarea')[0].setValue('synthetic selected context')
    await wrapper.findAll('textarea')[1].setValue('synthetic question')
    const grant = button(wrapper, '授权这份资料给 ChatGPT（一次）')
    expect(grant.element.disabled).toBe(true)
    await wrapper.find('input[type=checkbox]').setValue(true)
    await grant.trigger('click')
    await flushPromises()
    const call = fetch.mock.calls.find(([url, options]) => url.endsWith('/grant') && options?.method === 'POST')
    expect(call[1].body.cloud_ack).toBe(true)
    expect(call[1].body.text).toContain('synthetic selected context')
    expect(call[1].body.text).toContain('synthetic question')
    expect(wrapper.find('input[type=checkbox]').element.checked).toBe(false)
    expect(fetch.mock.calls.some(([url]) => url.endsWith('/chat'))).toBe(false)
    wrapper.unmount()
  })

  it('clears cloud acknowledgment when the preview changes and can revoke access', async () => {
    const { wrapper, fetch } = fixture()
    await flushPromises()
    await wrapper.find('input[type=checkbox]').setValue(true)
    await wrapper.findAll('textarea')[0].setValue('changed synthetic preview')
    expect(wrapper.find('input[type=checkbox]').element.checked).toBe(false)
    await button(wrapper, '撤销授权').trigger('click')
    await flushPromises()
    expect(fetch).toHaveBeenCalledWith('/api/offline/ai/grant', { method: 'DELETE' })
    wrapper.unmount()
  })
})
