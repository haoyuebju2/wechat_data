<template>
  <div class="flex flex-wrap items-center gap-3 border-b border-gray-200 px-4 py-2 text-xs dark:border-gray-700" role="status">
    <button type="button" class="rounded bg-blue-600 px-3 py-1.5 text-white disabled:opacity-50"
      :disabled="!account || busy || status.running || status.available === false" @click="refresh">
      {{ busy || status.running ? '正在本地更新…' : '更新最新记录' }}
    </button>
    <span>{{ description }}</span>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps({ account: { type: String, default: '' } })
const emit = defineEmits(['updated'])
const status = ref({})
const busy = ref(false)
const failed = ref(false)
let timer
let stream
let streamHealthy = false
let epoch = 0
let version = null
const description = computed(() => {
  if (!props.account) return '选择账号后可更新本地记录'
  if (failed.value) return '暂时无法检查更新，请重试'
  if (status.value.running) return '正在读取本机微信数据；校验完成后更新记录'
  if (status.value.available === false) return '此账号未关联本机微信源数据，需重新导入才能更新'
  const errors = status.value.errors || []
  if (errors.some(item => item.code === 'missing_local_key')) return '缺少本机保存的密钥，请在解密页面重新获取并解密'
  if (errors.length) return '部分数据尚未更新，已保留现有记录；稍后自动重试'
  const checked = status.value.checked_at
  return checked ? `本机消息自动更新 · 已检查 ${new Date(checked * 1000).toLocaleTimeString()}` : '本机消息自动更新，全程离线'
})

function applyStatus(next) {
  if (next.instance && status.value.instance && next.instance !== status.value.instance) version = null
  else if (Number(next.revision) < Number(status.value.revision)) return
  const changed = version === null ? next.version > 0 : next.version !== version
  version = next.version
  status.value = next
  if (changed) emit('updated')
}

function connect() {
  stream?.close()
  streamHealthy = false
  if (!props.account || typeof EventSource === 'undefined') return
  const current = epoch
  const next = new EventSource(`/api/offline/snapshot/events?account=${encodeURIComponent(props.account)}`)
  stream = next
  next.onopen = () => { if (current === epoch) streamHealthy = true }
  next.onmessage = event => {
    if (current !== epoch) return
    try { applyStatus(JSON.parse(event.data)); failed.value = false; streamHealthy = true } catch { streamHealthy = false }
  }
  next.onerror = () => { if (current === epoch) streamHealthy = false }
}

async function check() {
  const account = props.account
  const current = epoch
  if (!account) return
  try {
    const next = await $fetch('/api/offline/snapshot/status', { query: { account } })
    if (current !== epoch || account !== props.account) return
    failed.value = false
    applyStatus(next)
  } catch {
    if (current === epoch) failed.value = true
  }
}

async function refresh() {
  const account = props.account
  const current = epoch
  if (!account || busy.value) return
  busy.value = true
  try {
    const next = await $fetch('/api/offline/snapshot/refresh', { method: 'POST', body: { account } })
    if (current === epoch) { applyStatus(next); failed.value = false }
  } catch {
    if (current === epoch) failed.value = true
  } finally {
    if (current === epoch) busy.value = false
  }
}

watch(() => props.account, () => {
  epoch++
  version = null
  status.value = {}
  busy.value = false
  failed.value = false
  void check()
  connect()
}, { immediate: true })
onMounted(() => { timer = setInterval(() => { if (!streamHealthy) void check() }, 1000) })
onUnmounted(() => { epoch++; clearInterval(timer); stream?.close() })
</script>
