import type { Video } from '~/utils/release'

// The user's Discogs personal access token, kept in the browser only, never in
// the database. Set in settings, used by the /discogs search page

const token  = ref(storageGet('discogsToken'))
const user   = ref(storageGet('discogsUser'))
const status = ref<'idle' | 'checking' | 'ok' | 'error'>(token.value && user.value ? 'ok' : 'idle')

export const DISCOGS_API = 'https://api.discogs.com'

// one hit from /database/search
export interface DiscogsResult {
  id: number
  type: 'release' | 'master' | string
  title: string          // "Artist - Title"
  uri: string            // path on discogs.com
  resource_url?: string  // api url of the full record
  master_id?: number
  catno?: string
  format?: string[]
  year?: string
  cover_image?: string
  thumb?: string
}

// the parts of the full release / master record we use
export interface DiscogsDetails {
  videos?: Video[]
  labels?: { name: string }[]
}

export function useDiscogs() {
  function headers() {
    return { Authorization: `Discogs token=${token.value}` }
  }

  // check the token against the identity endpoint, keep it if it works
  async function verify(newToken: string) {
    status.value = 'checking'
    try {
      const res = await fetch(`${DISCOGS_API}/oauth/identity`, {
        headers: { Authorization: `Discogs token=${newToken}` },
      })
      if (!res.ok) { status.value = 'error'; return }
      const data   = await res.json()
      token.value  = newToken
      user.value   = data.username || ''
      status.value = 'ok'
      storageSet('discogsToken', token.value)
      storageSet('discogsUser',  user.value)
    } catch {
      status.value = 'error'
    }
  }

  return { token, user, status, headers, verify }
}
