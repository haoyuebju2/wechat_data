// A new URL on preview revalidates local variants without CDN or broad scans.
export const localImagePreviewUrl = (value, version = Date.now(), origin = globalThis.location?.origin || 'http://127.0.0.1:10392') => {
  const raw = String(value || '').trim()
  if (!raw) return raw
  try {
    const base = new URL(origin)
    const target = new URL(raw, base)
    if (target.origin !== base.origin || target.pathname !== '/api/chat/media/image' || target.username || target.password) return raw
    target.searchParams.set('prefer_live', 'false')
    target.searchParams.set('deep_scan', 'false')
    target.searchParams.set('fetch_remote', 'false')
    target.searchParams.set('v', String(version))
    return target.pathname + target.search
  } catch { return raw }
}
