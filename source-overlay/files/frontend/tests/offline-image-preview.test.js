import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { localImagePreviewUrl } from '~/lib/chat/local-image-preview'
import { useChatMessages } from '~/composables/chat/useChatMessages'
vi.mock('~/lib/server-error-logging', () => ({ reportServerError: vi.fn() }))
vi.mock('~/stores/chatAccounts', () => ({ useChatAccountsStore: () => ({ applySourceResponse: vi.fn() }) }))
afterEach(() => { vi.restoreAllMocks() })

describe('automatic local image preview', () => {
  it('revalidates the selected local image without remote download or a deep scan', () => {
    const url = new URL(localImagePreviewUrl('/api/chat/media/image?account=synthetic&md5=abc&record_index_path=1_2&fetch_remote=true', 123), 'http://127.0.0.1:10392')
    expect(url.searchParams.get('md5')).toBe('abc')
    expect(url.searchParams.get('record_index_path')).toBe('1_2')
    expect(url.searchParams.get('v')).toBe('123')
    expect(url.searchParams.get('fetch_remote')).toBe('false')
    expect(url.searchParams.get('deep_scan')).toBe('false')
    expect(url.searchParams.get('prefer_live')).toBe('false')
    expect(localImagePreviewUrl('https://example.invalid/image.png', 123)).toBe('https://example.invalid/image.png')
  })
  it('opening and switching previews rechecks only the current picture', () => {
    let state
    const wrapper = mount(defineComponent({ setup() {
      state = useChatMessages({ api: {}, apiBase: '/api', selectedAccount: ref('synthetic'),
        selectedContact: ref({ username: 'synthetic-friend' }), realtimeEnabled: ref(false),
        privacyMode: ref(false), searchContext: ref({ active: false }) })
      return () => h('div')
    } }))
    const first = '/api/chat/media/image?account=synthetic&md5=first'
    const second = '/api/chat/media/image?account=synthetic&md5=second'
    state.openImagePreview(first, [{ url: first }, { url: second }])
    expect(state.previewImageUrl.value).toContain('fetch_remote=false')
    expect(state.previewImageItems.value[1].url).toBe(second)
    state.showNextPreviewImage()
    expect(state.previewImageUrl.value).toContain('md5=second')
    expect(state.previewImageUrl.value).toContain('fetch_remote=false')
    wrapper.unmount()
  })
})
