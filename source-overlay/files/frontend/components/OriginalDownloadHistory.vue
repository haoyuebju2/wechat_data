<template>
  <aside class="original-history" aria-label="自动获取原图记录">
    <section v-if="open" id="original-history-panel" class="history-panel" aria-label="原图下载历史" @keydown.esc.stop="closePanel">
      <header>
        <div><h2>原图下载记录</h2><p>原图 {{ summary.downloaded }} · 清晰图 {{ summary.standard + summary.converted }} · 本地已有 {{ summary.local }} · 失败 {{ summary.failed }}</p></div>
        <button type="button" aria-label="关闭原图下载历史" @click="closePanel">×</button>
      </header>
      <div class="history-actions">
        <span>共 {{ summary.total }} 条历史</span>
        <div><button type="button" :disabled="loading || clearing" @click="loadHistory">刷新</button><button type="button" class="clear" :disabled="clearing || !summary.total" @click="clearHistory">{{ clearing ? '清空中…' : '清空历史' }}</button></div>
      </div>
      <p v-if="error" class="history-error" role="alert">{{ error }}</p>
      <div class="history-list" :aria-busy="loading || clearing">
        <p v-if="!items.length" class="history-empty">{{ loading ? '正在读取记录…' : '暂无自动获取原图的记录' }}</p>
        <ol v-else>
          <li v-for="item in items" :key="item.id">
            <div class="record-top"><strong>{{ privateMode ? '已隐藏对话' : item.conversation }}</strong><span :class="['record-status', item.status]">{{ statusLabel(item.status) }}</span></div>
            <p class="record-account">{{ privateMode ? '已隐藏账号' : item.account }}</p>
            <div class="record-bottom"><time :datetime="dateTime(item.finished_at)">{{ formatTime(item.finished_at) }}</time><span v-if="item.attempts">尝试 {{ item.attempts }} 次</span></div>
          </li>
        </ol>
        <button v-if="nextCursor" type="button" class="load-more" :disabled="loading || clearing" @click="loadMore">加载更早记录</button>
      </div>
      <footer>“新获取”包括原图和清晰转换图，打开后清零，历史仍保留。清空历史不删除图片或下载任务。转换图不等于原始文件，旧完成记录不计入新获取。</footer>
    </section>
    <button type="button" class="history-trigger" :aria-expanded="open" aria-controls="original-history-panel" :aria-label="`原图下载记录，新获取 ${summary.unread} 张`" @click="togglePanel">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="4"/><path d="m7 17 4-5 3 3 3-4 4 5"/><circle cx="8" cy="8" r="1"/></svg>
      <span>原图记录</span><span :class="['history-count', { fresh: summary.unread > 0 }]">新获取 {{ summary.unread }} 张</span><span aria-hidden="true">{{ open ? '⌃' : '⌄' }}</span>
    </button>
  </aside>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
defineProps({ privateMode: { type: Boolean, default: false } })
const emptySummary = () => ({ downloaded: 0, standard: 0, converted: 0, local: 0, failed: 0, completed: 0, cancelled: 0, total: 0, unread: 0 })
const summary = ref(emptySummary())
const items = ref([]), nextCursor = ref(null), open = ref(false), loading = ref(false), clearing = ref(false), error = ref('')
let alive = true, stream = null, fallback = null, requestEpoch = 0, summaryEpoch = 0, refreshQueued = false, hasLoaded = false
let controller = null
const base = '/api/offline/originals/history'
const statusLabel = status => ({ downloaded: '已下载原图', standard: '已下载清晰图', converted: '已下载转换图', local: '本地已有', failed: '获取失败', completed: '旧记录已完成', cancelled: '已停止' }[status] || '已处理')
const dateTime = timestamp => new Date(Number(timestamp) * 1000).toISOString()
const formatTime = timestamp => new Date(Number(timestamp) * 1000).toLocaleString()
async function api(url, options = {}) {
  const response = await fetch(url, options)
  if (!response.ok) throw new Error('History request failed')
  return response.json()
}
function mergeItems(latest) {
  const rows = new Map([...items.value, ...latest].map(item => [item.id, item]))
  items.value = [...rows.values()].sort((a, b) => Number(b.finished_at) - Number(a.finished_at) || b.id.localeCompare(a.id))
}
async function loadSummary() {
  if (open.value) return loadHistory()
  const epoch = ++summaryEpoch
  try {
    const value = await api(base + '/summary')
    if (alive && epoch === summaryEpoch && !open.value) summary.value = { ...emptySummary(), ...value }
  } catch { /* Keep the last count; opening the panel offers a visible retry. */ }
}
async function loadHistory() {
  if (!open.value || !alive) return
  if (loading.value || clearing.value) { refreshQueued = true; return }
  loading.value = true; error.value = ''; refreshQueued = false
  const epoch = ++requestEpoch
  controller = new AbortController()
  const signal = controller.signal
  try {
    const value = await api(base, { signal })
    if (!alive || !open.value || epoch !== requestEpoch) return
    if (!hasLoaded) { items.value = value.items || []; nextCursor.value = value.next_cursor; hasLoaded = true }
    else mergeItems(value.items || [])
    summary.value = { ...emptySummary(), ...value.summary }
    const marked = await api(base + '/seen', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ through: value.through }), signal })
    if (alive && open.value && epoch === requestEpoch) summary.value = { ...emptySummary(), ...marked }
  } catch {
    if (alive && open.value && epoch === requestEpoch && !signal.aborted) error.value = '记录读取或计数清零失败，请点“刷新”重试。'
  } finally {
    if (epoch === requestEpoch) {
      loading.value = false
      if (refreshQueued && open.value) { refreshQueued = false; void loadHistory() }
    }
  }
}
async function loadMore() {
  if (!nextCursor.value || loading.value || clearing.value) return
  loading.value = true; error.value = ''
  const epoch = ++requestEpoch
  controller = new AbortController()
  const signal = controller.signal
  try {
    const value = await api(base + '?cursor=' + encodeURIComponent(nextCursor.value), { signal })
    if (alive && open.value && epoch === requestEpoch) { mergeItems(value.items || []); nextCursor.value = value.next_cursor }
  } catch {
    if (alive && open.value && epoch === requestEpoch && !signal.aborted) error.value = '更早记录读取失败，请重试。'
  } finally {
    if (epoch === requestEpoch) {
      loading.value = false
      if (refreshQueued && open.value) { refreshQueued = false; void loadHistory() }
    }
  }
}
function closePanel() {
  open.value = false; ++requestEpoch; controller?.abort(); loading.value = false; refreshQueued = false
}
function togglePanel() {
  if (open.value) { closePanel(); return }
  open.value = true; items.value = []; hasLoaded = false; nextCursor.value = null
  void loadHistory()
}
async function clearHistory() {
  if (clearing.value) return
  ++requestEpoch; controller?.abort(); loading.value = false; clearing.value = true; error.value = ''
  try {
    const value = await api(base, { method: 'DELETE' })
    if (alive) {
      summary.value = { ...emptySummary(), ...value }; items.value = []; nextCursor.value = null; hasLoaded = false
      if (value.total) refreshQueued = true
    }
  } catch { if (alive) error.value = '历史未能清空，请重试；已有图片和下载队列不会被删除。' }
  finally {
    clearing.value = false
    if (refreshQueued && open.value) { refreshQueued = false; void loadHistory() }
  }
}
onMounted(() => {
  void loadSummary()
  if (typeof EventSource === 'function') {
    stream = new EventSource(base + '/events')
    stream.onmessage = () => { if (alive) void loadSummary() }
  } else fallback = setInterval(() => { if (alive) void loadSummary() }, 5000)
})
onUnmounted(() => { alive = false; ++requestEpoch; controller?.abort(); stream?.close(); if (fallback) clearInterval(fallback) })
</script>

<style scoped>
.original-history{position:relative;flex-shrink:0;z-index:15000;color:var(--app-text-primary,#223229);font-size:12px}.history-trigger{display:flex;align-items:center;gap:9px;border:1px solid var(--app-border,#dce5df);border-radius:12px;padding:10px 13px;background:var(--app-surface-bg,#fff);box-shadow:0 4px 22px #00000013;cursor:pointer}.history-count{color:var(--app-text-secondary,#788379);font-size:11px}.history-count.fresh{background:#e3f5e9;color:#087d3d;border-radius:12px;padding:3px 7px;font-weight:600}.history-panel{position:absolute;right:0;top:calc(100% + 10px);max-height:calc(100dvh - 110px);overflow-y:auto;width:min(420px,calc(100vw - 28px));background:var(--app-surface-bg,#fff);border:1px solid var(--app-border,#dce5df);border-radius:14px;box-shadow:0 12px 40px #00000022}.history-panel header{display:flex;justify-content:space-between;align-items:flex-start;padding:16px 16px 10px;gap:12px}.history-panel h2{font-size:14px;font-weight:600;margin:0 0 6px}.history-panel p{margin:0}.history-panel header p,.record-account,.record-bottom,.history-empty,.history-panel footer{color:var(--app-text-secondary,#7c867e)}.history-panel button{cursor:pointer}.history-panel header button{font-size:23px;line-height:20px;color:#888;border:0;background:none}.history-actions{display:flex;justify-content:space-between;align-items:center;padding:7px 16px 12px;border-bottom:1px solid var(--app-border,#eee)}.history-actions button{font-size:11px;background:none;border:0;margin-left:12px;color:#079b4a}.history-actions .clear{color:#ae4b40}.history-panel button:disabled{opacity:.4;cursor:default}.history-list{max-height:min(340px,46vh);overflow:auto}.history-list ol{list-style:none;margin:0;padding:0}.history-list li{padding:12px 16px;border-bottom:1px solid var(--app-border,#eee)}.record-top{display:flex;justify-content:space-between;align-items:center;gap:12px}.record-top strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500}.record-status{white-space:nowrap;font-size:11px;color:#828b84}.record-status.downloaded{color:#07894a}.record-status.failed{color:#bd4939}.record-account{font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:4px!important}.record-bottom{display:flex;justify-content:space-between;font-size:10px;margin-top:7px}.history-empty{text-align:center;padding:35px 12px}.history-error{padding:9px 16px;color:#b44936;background:#fff4ed}.history-panel footer{font-size:10px;line-height:1.6;padding:11px 16px;background:var(--app-surface-soft,#fafbf9)}.load-more{display:block;width:100%;padding:11px;background:none;color:#079b4a;border:0;font-size:11px}
</style>
