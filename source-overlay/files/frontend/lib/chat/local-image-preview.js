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

export const originalImageRequest = (value, origin = globalThis.location?.origin || 'http://127.0.0.1:10392', metadata = {}) => {
  try {
    const base = new URL(origin)
    const target = new URL(String(value || ''), base)
    if (target.origin !== base.origin || target.pathname !== '/api/chat/media/image' || target.username || target.password) return null
    const account = target.searchParams.get('account') || String(metadata.account || '')
    const username = target.searchParams.get('username') || String(metadata.username || '')
    const server_id = target.searchParams.get('server_id') || String(metadata.server_id || '')
    if (!account || !username || !/^-?[1-9][0-9]{0,19}$/.test(server_id)) return null
    return { account, username, server_id, md5: target.searchParams.get('md5') || '' }
  } catch { return null }
}
