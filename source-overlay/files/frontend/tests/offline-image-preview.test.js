import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { localImagePreviewUrl, originalImageRequest } from '~/lib/chat/local-image-preview'
import { useChatMessages } from '~/composables/chat/useChatMessages'
vi.mock('~/lib/server-error-logging', () => ({ reportServerError: vi.fn() }))
vi.mock('~/stores/chatAccounts', () => ({ useChatAccountsStore: () => ({ applySourceResponse: vi.fn() }) }))
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('automatic local image preview', () => {
  it('only derives owned message identifiers from same-origin image URLs', () => {
    expect(originalImageRequest('/api/chat/media/image?account=test&username=friend&server_id=9007199254740993&md5=abc')).toEqual({ account: 'test', username: 'friend', server_id: '9007199254740993', md5: 'abc' })
    expect(originalImageRequest('https://example.invalid/api/chat/media/image?account=test&username=friend&server_id=42')).toBeNull()
    expect(originalImageRequest('/api/chat/media/emoji?account=test&username=friend&server_id=42')).toBeNull()
    expect(originalImageRequest('/api/chat/media/image?account=test&username=friend')).toBeNull()
    expect(originalImageRequest('/api/chat/media/image?account=test&username=friend&server_id=-9007199254740993')?.server_id).toBe('-9007199254740993')
  })
  it('downloads only the opened image and ignores results after closing preview', async () => {
    let state, resolveResult
    const fetchMock = vi.fn(() => new Promise(resolve => { resolveResult = resolve }))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(defineComponent({ setup() {
      state = useChatMessages({ api: {}, apiBase: '/api', selectedAccount: ref('synthetic'), selectedContact: ref({ username: 'friend' }), realtimeEnabled: ref(false), privacyMode: ref(false), searchContext: ref({ active: false }) })
      return () => h('div')
    } }))
    expect(fetchMock).not.toHaveBeenCalled()
    const imageUrl = '/api/chat/media/image?account=synthetic&username=friend&md5=abc'
    state.openImagePreview(imageUrl, [{ url: imageUrl, serverIdStr: '9007199254740993' }])
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).server_id).toBe('9007199254740993')
    expect(state.previewImageOriginalStatus.value).toBe('正在获取原图…')
    state.closeImagePreview()
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true)
    resolveResult({ ok: true, json: async () => ({ ok: true, message: '已获取原图' }) })
    await flushPromises()
    expect(state.previewImageUrl.value).toBeNull()
    expect(state.previewImageOriginalStatus.value).toBe('')
    wrapper.unmount()
  })
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
