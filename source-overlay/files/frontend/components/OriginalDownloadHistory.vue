<template>
  <aside ref="floatingRoot" :class="['original-history', { dragging, collapsed }]" :data-dock="position.dock || 'none'" :style="floatingStyle" aria-label="自动获取原图记录">
    <section v-if="open" id="original-history-panel" class="history-panel" :style="panelStyle" aria-label="原图下载历史" @keydown.esc.stop="closePanel">
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
    <button ref="triggerButton" type="button" class="history-trigger" :aria-expanded="open" aria-controls="original-history-panel" :aria-label="`原图下载记录，新获取 ${summary.unread} 张`" title="拖动调整位置，靠边收起；点击查看记录" @pointerdown="startDrag" @click="clickTrigger" @keydown.esc.stop="closePanel">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="4"/><path d="m7 17 4-5 3 3 3-4 4 5"/><circle cx="8" cy="8" r="1"/></svg>
      <span v-show="!collapsed">原图记录</span><span v-show="!collapsed" :class="['history-count', { fresh: summary.unread > 0 }]">新获取 {{ summary.unread }} 张</span><span v-show="!collapsed" aria-hidden="true">{{ open ? '⌃' : '⌄' }}</span>
      <span v-if="collapsed && summary.unread > 0" class="dock-dot" aria-hidden="true" />
    </button>
  </aside>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
defineProps({ privateMode: { type: Boolean, default: false } })
const emptySummary = () => ({ downloaded: 0, standard: 0, converted: 0, local: 0, failed: 0, completed: 0, cancelled: 0, total: 0, unread: 0 })
const summary = ref(emptySummary())
const items = ref([]), nextCursor = ref(null), open = ref(false), loading = ref(false), clearing = ref(false), error = ref('')
const floatingRoot = ref(null), triggerButton = ref(null), dragging = ref(false)
const viewport = ref({ width: 1280, height: 860 })
const position = ref({ x: 1142, y: 32, dock: null })
const positionKey = 'ui.originalHistory.position.v1'
const margin = 8, dockSize = 48
const clamp = (value, min, max) => Math.max(min, Math.min(Math.max(min, max), value))
const collapsed = computed(() => !!position.value.dock && !open.value && !dragging.value)
const triggerWidth = computed(() => Math.min(244, Math.max(48, viewport.value.width - 16)))
const bounds = computed(() => {
  const { width: vw, height: vh } = viewport.value
  const { x, y, dock } = position.value
  if (collapsed.value) {
    return { x: dock === 'left' ? -24 : dock === 'right' ? vw - 24 : clamp(x - 24, margin, vw - 48 - margin),
      y: dock === 'top' ? -24 : dock === 'bottom' ? vh - 24 : clamp(y - 24, margin, vh - 48 - margin), width: dockSize, height: dockSize }
  }
  return { x: clamp(x - triggerWidth.value / 2, margin, vw - triggerWidth.value - margin), y: clamp(y - 23, margin, vh - 46 - margin), width: triggerWidth.value, height: 46 }
})
const floatingStyle = computed(() => ({ left: `${bounds.value.x}px`, top: `${bounds.value.y}px`, width: `${bounds.value.width}px`, height: `${bounds.value.height}px` }))
const panelStyle = computed(() => {
  const b = bounds.value, width = Math.min(420, viewport.value.width - margin * 2)
  const below = viewport.value.height - b.y - b.height - margin - 10, above = b.y - margin - 10
  return { left: `${clamp(b.x + b.width - width, margin, viewport.value.width - width - margin)}px`, width: `${width}px`,
    ...(below >= above ? { top: `${b.y + b.height + 10}px`, maxHeight: `${Math.max(0, below)}px` } : { bottom: `${viewport.value.height - b.y + 10}px`, maxHeight: `${Math.max(0, above)}px` }) }
})
let gesture = null, suppressClick = false, clickTimer = null, positionEdited = false
function savePosition() {
  const value = { version: 1, x: clamp(position.value.x / viewport.value.width, 0, 1), y: clamp(position.value.y / viewport.value.height, 0, 1), dock: position.value.dock }
  try { localStorage.setItem(positionKey, JSON.stringify(value)) } catch { /* The control also works when local storage is disabled. */ }
  try { void window.wechatDesktop?.setOriginalHistoryPosition?.(value)?.catch(() => {}) } catch { /* Saving placement must not affect downloads. */ }
}
function startDrag(event) {
  if (event.button !== 0 || event.isPrimary === false || gesture) return
  const b = bounds.value
  gesture = { id: event.pointerId, startX: event.clientX, startY: event.clientY, offsetX: event.clientX - b.x - b.width / 2,
    offsetY: event.clientY - b.y - b.height / 2, origin: { ...position.value }, fromDock: collapsed.value }
  try { triggerButton.value.setPointerCapture(event.pointerId) } catch { /* Window listeners cover browsers without pointer capture. */ }
}
function moveDrag(event) {
  if (!gesture || event.pointerId !== gesture.id) return
  if (!dragging.value && Math.hypot(event.clientX - gesture.startX, event.clientY - gesture.startY) < 6) return
  if (!dragging.value) {
    closePanel(); dragging.value = true; positionEdited = true
    if (gesture.fromDock) { gesture.offsetX = 0; gesture.offsetY = 0 }
  }
  event.preventDefault()
  position.value = { x: clamp(event.clientX - gesture.offsetX, margin + triggerWidth.value / 2, viewport.value.width - margin - triggerWidth.value / 2),
    y: clamp(event.clientY - gesture.offsetY, margin + 23, viewport.value.height - margin - 23), dock: null }
}
function endDrag(event) {
  if (!gesture || event.pointerId !== gesture.id) return
  if (dragging.value) {
    // Account for the last pointer-up position even if its move was coalesced.
    moveDrag(event)
    const b = bounds.value
    const [dock, distance] = [['left', b.x], ['right', viewport.value.width - b.x - b.width], ['top', b.y], ['bottom', viewport.value.height - b.y - b.height]].sort((a, b) => a[1] - b[1])[0]
    if (distance <= 20) {
      position.value.dock = dock
      if (dock === 'left' || dock === 'right') position.value.x = dock === 'left' ? 0 : viewport.value.width
      else position.value.y = dock === 'top' ? 0 : viewport.value.height
    }
    savePosition(); suppressClick = true
    clearTimeout(clickTimer); clickTimer = setTimeout(() => { suppressClick = false }, 0)
  }
  try { triggerButton.value.releasePointerCapture(gesture.id) } catch { /* Capture may already have been released. */ }
  gesture = null; dragging.value = false
}
function cancelDrag(event) {
  if (!gesture || (event && event.pointerId !== gesture.id)) return
  position.value = gesture.origin
  try { triggerButton.value?.releasePointerCapture(gesture.id) } catch { /* Ignore an already released capture. */ }
  gesture = null; dragging.value = false
}
function clickTrigger() {
  if (suppressClick) return
  togglePanel()
}
function outsidePointer(event) {
  if (open.value && !floatingRoot.value?.contains(event.target)) closePanel()
}
function cancelGesture() { cancelDrag() }
function applyStoredPosition(stored) {
  if (stored?.version === 1 && Number.isFinite(stored.x) && Number.isFinite(stored.y) && stored.x >= 0 && stored.x <= 1 && stored.y >= 0 && stored.y <= 1 && [null, 'left', 'right', 'top', 'bottom'].includes(stored.dock)) {
    position.value = { x: stored.x * viewport.value.width, y: stored.y * viewport.value.height, dock: stored.dock }
  }
}
function resizeViewport() {
  cancelDrag()
  const previous = viewport.value
  viewport.value = { width: Math.max(64, window.innerWidth), height: Math.max(64, window.innerHeight) }
  position.value = { ...position.value, x: position.value.x / previous.width * viewport.value.width, y: position.value.y / previous.height * viewport.value.height }
}
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
  viewport.value = { width: Math.max(64, window.innerWidth), height: Math.max(64, window.innerHeight) }
  const notice = document.querySelector('.offline-notice')?.getBoundingClientRect()
  position.value = { x: viewport.value.width - triggerWidth.value / 2 - 16, y: notice?.height ? notice.top + notice.height / 2 : 32, dock: null }
  try {
    const stored = JSON.parse(localStorage.getItem(positionKey))
    applyStoredPosition(stored)
  } catch { /* Ignore malformed or unavailable local preferences. */ }
  try {
    void window.wechatDesktop?.getOriginalHistoryPosition?.()?.then(stored => { if (alive && !positionEdited) applyStoredPosition(stored) }).catch(() => {})
  } catch { /* The browser version uses its local preference instead. */ }
  window.addEventListener('pointermove', moveDrag, { passive: false })
  window.addEventListener('pointerup', endDrag)
  window.addEventListener('pointercancel', cancelDrag)
  window.addEventListener('resize', resizeViewport)
  window.addEventListener('blur', cancelGesture)
  document.addEventListener('pointerdown', outsidePointer)
  void loadSummary()
  if (typeof EventSource === 'function') {
    stream = new EventSource(base + '/events')
    stream.onmessage = () => { if (alive) void loadSummary() }
  } else fallback = setInterval(() => { if (alive) void loadSummary() }, 5000)
})
onUnmounted(() => {
  alive = false; ++requestEpoch; controller?.abort(); stream?.close(); if (fallback) clearInterval(fallback)
  cancelDrag(); clearTimeout(clickTimer)
  window.removeEventListener('pointermove', moveDrag)
  window.removeEventListener('pointerup', endDrag)
  window.removeEventListener('pointercancel', cancelDrag)
  window.removeEventListener('resize', resizeViewport)
  window.removeEventListener('blur', cancelGesture)
  document.removeEventListener('pointerdown', outsidePointer)
})
</script>

<style scoped>
.original-history{position:relative;flex-shrink:0;z-index:15000;color:var(--app-text-primary,#223229);font-size:12px}.history-trigger{display:flex;align-items:center;gap:9px;border:1px solid var(--app-border,#dce5df);border-radius:12px;padding:10px 13px;background:var(--app-surface-bg,#fff);box-shadow:0 4px 22px #00000013;cursor:pointer}.history-count{color:var(--app-text-secondary,#788379);font-size:11px}.history-count.fresh{background:#e3f5e9;color:#087d3d;border-radius:12px;padding:3px 7px;font-weight:600}.history-panel{position:absolute;right:0;top:calc(100% + 10px);max-height:calc(100dvh - 110px);overflow-y:auto;width:min(420px,calc(100vw - 28px));background:var(--app-surface-bg,#fff);border:1px solid var(--app-border,#dce5df);border-radius:14px;box-shadow:0 12px 40px #00000022}.history-panel header{display:flex;justify-content:space-between;align-items:flex-start;padding:16px 16px 10px;gap:12px}.history-panel h2{font-size:14px;font-weight:600;margin:0 0 6px}.history-panel p{margin:0}.history-panel header p,.record-account,.record-bottom,.history-empty,.history-panel footer{color:var(--app-text-secondary,#7c867e)}.history-panel button{cursor:pointer}.history-panel header button{font-size:23px;line-height:20px;color:#888;border:0;background:none}.history-actions{display:flex;justify-content:space-between;align-items:center;padding:7px 16px 12px;border-bottom:1px solid var(--app-border,#eee)}.history-actions button{font-size:11px;background:none;border:0;margin-left:12px;color:#079b4a}.history-actions .clear{color:#ae4b40}.history-panel button:disabled{opacity:.4;cursor:default}.history-list{max-height:min(340px,46vh);overflow:auto}.history-list ol{list-style:none;margin:0;padding:0}.history-list li{padding:12px 16px;border-bottom:1px solid var(--app-border,#eee)}.record-top{display:flex;justify-content:space-between;align-items:center;gap:12px}.record-top strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500}.record-status{white-space:nowrap;font-size:11px;color:#828b84}.record-status.downloaded{color:#07894a}.record-status.failed{color:#bd4939}.record-account{font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:4px!important}.record-bottom{display:flex;justify-content:space-between;font-size:10px;margin-top:7px}.history-empty{text-align:center;padding:35px 12px}.history-error{padding:9px 16px;color:#b44936;background:#fff4ed}.history-panel footer{font-size:10px;line-height:1.6;padding:11px 16px;background:var(--app-surface-soft,#fafbf9)}.load-more{display:block;width:100%;padding:11px;background:none;color:#079b4a;border:0;font-size:11px}
.original-history{position:fixed;flex-shrink:0;transition:left .16s ease,top .16s ease,width .16s ease,height .16s ease;-webkit-app-region:no-drag}
.original-history.dragging{transition:none}
.history-trigger{box-sizing:border-box;width:100%;height:100%;padding:10px 12px;gap:8px;white-space:nowrap;touch-action:none;user-select:none;cursor:grab;color:inherit;transition:border-radius .16s ease}
.history-trigger:focus-visible{outline:2px solid #07a654;outline-offset:2px}
.history-trigger svg{flex-shrink:0}
.history-count{min-width:0;overflow:hidden;text-overflow:ellipsis}
.dragging .history-trigger{cursor:grabbing}
.history-panel{position:fixed;right:auto;top:auto;box-sizing:border-box;overscroll-behavior:contain}
.collapsed .history-trigger{position:relative;border-radius:50%;padding:4px;gap:0;box-shadow:0 3px 14px #00000020}
.collapsed[data-dock=left] .history-trigger{justify-content:flex-end}
.collapsed[data-dock=right] .history-trigger{justify-content:flex-start}
.collapsed[data-dock=top] .history-trigger{align-items:flex-end;justify-content:center}
.collapsed[data-dock=bottom] .history-trigger{align-items:flex-start;justify-content:center}
.dock-dot{position:absolute;width:6px;height:6px;border-radius:50%;background:#07a654;right:5px;top:5px;box-shadow:0 0 0 1px var(--app-surface-bg,#fff)}
[data-dock=right] .dock-dot{left:5px;right:auto}
[data-dock=top] .dock-dot{top:auto;bottom:4px}
@media(prefers-reduced-motion:reduce){.original-history,.history-trigger{transition:none}}
</style>
