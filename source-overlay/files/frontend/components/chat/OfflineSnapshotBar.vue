<template><!-- Background synchronization deliberately has no visible status bar. --></template>

<script setup>
import { onMounted, onUnmounted, watch } from 'vue'

const props = defineProps({ account: { type: String, default: '' } })
const emit = defineEmits(['updated'])
let status = {}
let timer
let stream
let streamHealthy = false
let epoch = 0
let version = null

function applyStatus(next) {
  if (next.instance && status.instance && next.instance !== status.instance) version = null
  else if (Number(next.revision) < Number(status.revision)) return
  const changed = version === null ? next.version > 0 : next.version !== version
  version = next.version
  status = next
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
    try { applyStatus(JSON.parse(event.data)); streamHealthy = true } catch { streamHealthy = false }
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
    applyStatus(next)
  } catch { /* The event stream reconnects; the fallback check retries. */ }
}

watch(() => props.account, () => {
  epoch++
  version = null
  status = {}
  void check()
  connect()
}, { immediate: true })
onMounted(() => { timer = setInterval(() => { if (!streamHealthy) void check() }, 1000) })
onUnmounted(() => { epoch++; clearInterval(timer); stream?.close() })
</script>