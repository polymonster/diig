// localStorage helpers that never throw: a missing, corrupt or blocked value
// (private browsing, cleared site data) reads as the fallback.
//
// Strings are stored raw and everything else as JSON, matching what older
// versions of the site wrote, so existing saved preferences keep working.

export function storageGet(key: string, fallback = ''): string {
  try { return localStorage.getItem(key) ?? fallback }
  catch { return fallback }
}

export function storageGetJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) as T : fallback
  } catch {
    return fallback
  }
}

export function storageSet(key: string, value: unknown) {
  try { localStorage.setItem(key, typeof value === 'string' ? value : JSON.stringify(value)) }
  catch {}
}

// everything this site keeps in the browser: the diig_ prefixed preferences
// plus a few older unprefixed keys. used on account deletion
const LEGACY_KEYS = ['discogsToken', 'discogsUser', 'showDebug']

export function storageClearAll() {
  try {
    const keys = Object.keys(localStorage).filter(k => k.startsWith('diig_') || LEGACY_KEYS.includes(k))
    for (const k of keys) localStorage.removeItem(k)
  } catch {}
}
