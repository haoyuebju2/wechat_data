import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import OriginalDownloadHistory from '~/components/OriginalDownloadHistory.vue'

afterEach(() => { localStorage.clear(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
function fixture() {
  const state = { rows: [], seen: 0, sequence: 0, failSeen: false }
  function add(status = 'downloaded') {
    const seq = ++state.sequence
    state.rows.unshift({ id: 'synthetic:' + seq, account: 'synthetic', conversation: '示例出游群', status, finished_at: 1700000000 + seq, attempts: 1, seq })
  }
  add(); add(); add('local')
  const summary = () => ({ downloaded: state.rows.filter(x => x.status === 'downloaded').length, local: state.rows.filter(x => x.status === 'local').length,
    standard: state.rows.filter(x => x.status === 'standard').length, converted: state.rows.filter(x => x.status === 'converted').length,
    total: state.rows.length, unread: state.rows.filter(x => ['downloaded','standard','converted'].includes(x.status) && x.seq > state.seen).length })
  const streams = []
  vi.stubGlobal('EventSource', class { constructor() { this.close = vi.fn(); streams.push(this) } })
  const fetch = vi.fn(async (url, options = {}) => {
    if (url.endsWith('/summary')) return { ok: true, json: async () => summary() }
    if (url.endsWith('/seen')) {
      if (state.failSeen) return { ok: false }
      state.seen = Math.max(state.seen, JSON.parse(options.body).through.synthetic)
      return { ok: true, json: async () => summary() }
    }
    if (options.method === 'DELETE') { state.rows = []; return { ok: true, json: async () => summary() } }
    return { ok: true, json: async () => ({ items: state.rows.map(x => ({ ...x })), through: { synthetic: state.sequence }, next_cursor: null, summary: summary() }) }
  })
  vi.stubGlobal('fetch', fetch)
  const wrapper = mount(OriginalDownloadHistory)
  return { state, add, summary, streams, fetch, wrapper }
}
const trigger = wrapper => wrapper.get('button[aria-controls="original-history-panel"]')
const clearButton = wrapper => wrapper.findAll('button').find(x => x.text() === '清空历史')
const positionKey = 'ui.originalHistory.position.v1'
const pointer = (target, type, x, y) => target.dispatchEvent(new PointerEvent(type, { pointerId: 7, button: 0, isPrimary: true, clientX: x, clientY: y, bubbles: true, cancelable: true }))
function dragTo(wrapper, x, y) {
  const root = wrapper.get('aside').element, button = trigger(wrapper).element
  const left = parseFloat(root.style.left), top = parseFloat(root.style.top)
  const width = parseFloat(root.style.width), height = parseFloat(root.style.height)
  const startX = Math.max(1, Math.min(window.innerWidth - 1, left + width / 2))
  const startY = Math.max(1, Math.min(window.innerHeight - 1, top + height / 2))
  pointer(button, 'pointerdown', startX, startY)
  pointer(window, 'pointermove', x, y)
  pointer(window, 'pointerup', x, y)
  // Browsers may dispatch a click after pointer-up, even after a drag.
  button.click()
}

describe('original download history popover', () => {
  it('loads counts only until opened, then acknowledges the snapshot without deleting history', async () => {
    const { wrapper, fetch, state, streams } = fixture()
    await flushPromises()
    expect(wrapper.text()).toContain('新获取 2 张')
    expect(wrapper.find('section').exists()).toBe(false)
    expect(fetch.mock.calls.every(([url]) => url.endsWith('/summary'))).toBe(true)
    await trigger(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('新获取 0 张')
    expect(wrapper.findAll('li')).toHaveLength(3)
    expect(state.rows).toHaveLength(3)
    expect(fetch.mock.calls.filter(([, options]) => options.method === 'DELETE')).toHaveLength(0)
    await wrapper.get('button[aria-label="关闭原图下载历史"]').trigger('click')
    await trigger(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.findAll('li')).toHaveLength(3)
    wrapper.unmount(); expect(streams[0].close).toHaveBeenCalled()
  })
  it('clears history separately and counts subsequent downloads from zero', async () => {
    const { wrapper, fetch, add, streams } = fixture()
    await flushPromises(); await trigger(wrapper).trigger('click'); await flushPromises()
    await clearButton(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('共 0 条历史')
    expect(wrapper.findAll('li')).toHaveLength(0)
    expect(fetch.mock.calls.some(([url, options]) => url.endsWith('/history') && options.method === 'DELETE')).toBe(true)
    expect(fetch.mock.calls.every(([url]) => url.startsWith('/api/offline/originals/history'))).toBe(true)
    await trigger(wrapper).trigger('click')
    add(); streams[0].onmessage({ data: '{"revision":2}' }); await flushPromises()
    expect(wrapper.text()).toContain('新获取 1 张')
    await trigger(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('新获取 0 张')
    expect(wrapper.findAll('li')).toHaveLength(1)
    wrapper.unmount()
  })
  it('does not claim the count reset when acknowledgement failed', async () => {
    const { wrapper, state } = fixture(); state.failSeen = true
    await flushPromises(); await trigger(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('新获取 2 张')
    expect(wrapper.get('[role=alert]').text()).toContain('计数清零失败')
    expect(wrapper.findAll('li')).toHaveLength(3)
    wrapper.unmount()
  })
  it('does not acknowledge or paint a late history response after closing', async () => {
    const { wrapper, fetch } = fixture()
    await flushPromises()
    let complete
    fetch.mockImplementationOnce(() => new Promise(resolve => { complete = resolve }))
    await trigger(wrapper).trigger('click')
    await wrapper.get('button[aria-label="关闭原图下载历史"]').trigger('click')
    complete({ ok: true, json: async () => ({ items: [], through: { synthetic: 3 }, summary: { unread: 0 } }) })
    await flushPromises()
    expect(wrapper.find('section').exists()).toBe(false)
    expect(wrapper.text()).toContain('新获取 2 张')
    expect(fetch.mock.calls.some(([url]) => url.endsWith('/seen'))).toBe(false)
    wrapper.unmount()
  })
  it('masks conversation and account names in privacy mode', async () => {
    const { wrapper } = fixture()
    await wrapper.setProps({ privateMode: true }); await flushPromises()
    await trigger(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('已隐藏对话')
    expect(wrapper.text()).not.toContain('示例出游群')
    expect(wrapper.html()).not.toContain('synthetic')
    wrapper.unmount()
  })
  it('shows converted previews separately from original files', async () => {
    const { wrapper, add } = fixture(); add('converted')
    await flushPromises(); await trigger(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('原图 2 · 清晰图 1')
    expect(wrapper.text()).toContain('已下载转换图')
    expect(wrapper.text()).toContain('转换图不等于原始文件')
    wrapper.unmount()
  })
  it('moves without opening history or acknowledging downloads, and restores the position', async () => {
    const { wrapper, fetch } = fixture(); await flushPromises()
    dragTo(wrapper, window.innerWidth / 2, window.innerHeight / 2)
    await flushPromises()
    expect(wrapper.get('aside').attributes('data-dock')).toBe('none')
    expect(wrapper.find('section').exists()).toBe(false)
    expect(fetch.mock.calls.every(([url]) => url.endsWith('/summary'))).toBe(true)
    const stored = JSON.parse(localStorage.getItem(positionKey))
    expect(stored).toEqual({ version: 1, x: 0.5, y: 0.5, dock: null })
    const left = wrapper.get('aside').element.style.left
    wrapper.unmount()
    const restored = fixture(); await flushPromises()
    expect(restored.wrapper.get('aside').element.style.left).toBe(left)
    restored.wrapper.unmount()
  })
  it.each(['left', 'right', 'top', 'bottom'])('collapses at the %s edge, expands on click and undocks by dragging', async edge => {
    localStorage.setItem(positionKey, JSON.stringify({ version: 1, x: 0.5, y: 0.5, dock: null }))
    const { wrapper, state } = fixture(); await flushPromises()
    const vw = window.innerWidth, vh = window.innerHeight
    const targets = { left: [0, vh / 2], right: [vw, vh / 2], top: [vw / 2, 0], bottom: [vw / 2, vh] }
    dragTo(wrapper, ...targets[edge]); await flushPromises()
    expect(wrapper.get('aside').attributes('data-dock')).toBe(edge)
    expect(wrapper.get('aside').classes()).toContain('collapsed')
    expect(state.seen).toBe(0)
    expect(wrapper.get('aside').element.style.width).toBe('48px')
    if (edge === 'left') expect(wrapper.get('aside').element.style.left).toBe('-24px')
    if (edge === 'right') expect(wrapper.get('aside').element.style.left).toBe(`${vw - 24}px`)
    if (edge === 'top') expect(wrapper.get('aside').element.style.top).toBe('-24px')
    if (edge === 'bottom') expect(wrapper.get('aside').element.style.top).toBe(`${vh - 24}px`)
    await new Promise(resolve => setTimeout(resolve, 0))
    await trigger(wrapper).trigger('click'); await flushPromises()
    expect(wrapper.get('aside').classes()).not.toContain('collapsed')
    expect(wrapper.get('section').exists()).toBe(true)
    expect(state.seen).toBe(3)
    const panel = wrapper.get('section').element.style
    expect(parseFloat(panel.left)).toBeGreaterThanOrEqual(8)
    expect(parseFloat(panel.left) + parseFloat(panel.width)).toBeLessThanOrEqual(vw - 8)
    await wrapper.get('button[aria-label="关闭原图下载历史"]').trigger('click')
    expect(wrapper.get('aside').classes()).toContain('collapsed')
    dragTo(wrapper, vw / 2, vh / 2); await flushPromises()
    expect(wrapper.get('aside').attributes('data-dock')).toBe('none')
    expect(wrapper.get('aside').classes()).not.toContain('collapsed')
    expect(wrapper.find('section').exists()).toBe(false)
    wrapper.unmount()
  })
  it('cancels an interrupted drag and keeps the saved position', async () => {
    const saved = JSON.stringify({ version: 1, x: 0.5, y: 0.5, dock: null })
    localStorage.setItem(positionKey, saved)
    const { wrapper } = fixture(); await flushPromises()
    const before = wrapper.get('aside').element.style.left
    pointer(trigger(wrapper).element, 'pointerdown', window.innerWidth / 2, window.innerHeight / 2)
    pointer(window, 'pointermove', 100, 100); await flushPromises()
    pointer(window, 'pointercancel', 100, 100); await flushPromises()
    expect(wrapper.get('aside').element.style.left).toBe(before)
    expect(localStorage.getItem(positionKey)).toBe(saved)
    wrapper.unmount()
  })
  it('uses the desktop position store across mounts without opening or acknowledging history', async () => {
    let saved = { version: 1, x: 0.3, y: 0.6, dock: 'left' }
    const bridge = { getOriginalHistoryPosition: vi.fn(async () => saved), setOriginalHistoryPosition: vi.fn(async value => { saved = value }) }
    vi.stubGlobal('wechatDesktop', bridge)
    const first = fixture(); await flushPromises()
    expect(first.wrapper.get('aside').attributes('data-dock')).toBe('left')
    dragTo(first.wrapper, window.innerWidth / 2, window.innerHeight / 2); await flushPromises()
    expect(bridge.setOriginalHistoryPosition).toHaveBeenCalledWith({ version: 1, x: 0.5, y: 0.5, dock: null })
    first.wrapper.unmount(); localStorage.clear()
    const second = fixture(); await flushPromises()
    expect(second.wrapper.get('aside').attributes('data-dock')).toBe('none')
    expect(parseFloat(second.wrapper.get('aside').element.style.left)).toBe(window.innerWidth / 2 - 122)
    expect(second.state.seen).toBe(0)
    second.wrapper.unmount()
  })
  it('ignores invalid preferences and keeps the control and panel inside a resized window', async () => {
    localStorage.setItem(positionKey, '{"version":1,"x":-200,"y":8,"dock":"invalid"}')
    const { wrapper } = fixture(); await flushPromises()
    dragTo(wrapper, window.innerWidth / 2, window.innerHeight / 2); await flushPromises()
    vi.stubGlobal('innerWidth', 360); vi.stubGlobal('innerHeight', 480)
    window.dispatchEvent(new Event('resize')); await flushPromises()
    const root = wrapper.get('aside').element.style
    expect(parseFloat(root.left)).toBeGreaterThanOrEqual(8)
    expect(parseFloat(root.left) + parseFloat(root.width)).toBeLessThanOrEqual(352)
    await new Promise(resolve => setTimeout(resolve, 0))
    await trigger(wrapper).trigger('click'); await flushPromises()
    const panel = wrapper.get('section').element.style
    expect(parseFloat(panel.left) + parseFloat(panel.width)).toBeLessThanOrEqual(352)
    expect(parseFloat(panel.maxHeight)).toBeGreaterThan(0)
    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
    await flushPromises()
    expect(wrapper.find('section').exists()).toBe(false)
    wrapper.unmount()
  })
})
