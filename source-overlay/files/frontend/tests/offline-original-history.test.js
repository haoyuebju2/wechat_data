import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import OriginalDownloadHistory from '~/components/OriginalDownloadHistory.vue'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
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
})
