import { useFirebaseAuth } from 'vuefire'

// Firebase realtime database root, shared with scripts/og-live.mjs
export const DB = 'https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app'

// Thin wrappers over the realtime database REST API. Paths are relative to the
// root without the .json suffix, e.g. get(`users/${uid}/likes`). Requests are
// signed with the current user's id token when someone is signed in.
//
// get returns null for a missing node or a failed request (rules denied,
// network error), so callers only need to handle "no data".
export function useDb() {
  const auth = useFirebaseAuth()

  async function url(path: string, query: Record<string, string> = {}): Promise<string> {
    const params = new URLSearchParams(query)
    const token  = await auth?.currentUser?.getIdToken()
    if (token) params.set('auth', token)
    return `${DB}/${path}.json?${params}`
  }

  async function get<T = any>(path: string, query?: Record<string, string>): Promise<T | null> {
    try {
      const res = await fetch(await url(path, query), { cache: 'no-store' })
      return res.ok ? await res.json() as T : null
    } catch (e) {
      console.error('db get', path, e)
      return null
    }
  }

  async function write(method: 'PUT' | 'PATCH', path: string, value: unknown): Promise<boolean> {
    const res = await fetch(await url(path), {
      method,
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(value),
    })
    return res.ok
  }

  // replace the node at path
  const put = (path: string, value: unknown) => write('PUT', path, value)

  // multi-path update, keys are paths relative to path
  const patch = (path: string, value: Record<string, unknown>) => write('PATCH', path, value)

  return { get, put, patch }
}
