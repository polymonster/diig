import { useFirebaseAuth } from 'vuefire'
import type { Release } from '~/utils/release'

// Module-level singletons, like usePlayer: one set of likes for the whole app,
// so a like from the player shows on the tiles and the other way round

const likes = ref<Record<string, number>>({})  // id -> timestamp, 0 is an un-like

// the load in flight or done for the signed in user, so app.vue and a page
// asking at the same time share one request
let loading: Promise<void> | null = null
let loadedUid: string | null = null

export function useLikes() {
  const auth = useFirebaseAuth()
  const db   = useDb()

  function isLiked(id: string) { return (likes.value[id] ?? 0) > 0 }

  function loadLikes(force = false): Promise<void> {
    const uid = auth?.currentUser?.uid ?? null
    if (!uid) {
      // signed out, nothing of the last user's should show
      likes.value = {}
      loading = null
      loadedUid = null
      return Promise.resolve()
    }
    if (loading && loadedUid === uid && !force) return loading

    loadedUid = uid
    loading = (async () => {
      const data  = await db.get(`users/${uid}/likes`)
      likes.value = data && typeof data === 'object' ? data : {}
    })()
    return loading
  }

  async function toggleLike(release: Release) {
    const uid = auth?.currentUser?.uid
    const id  = release?.id
    if (!uid || !id) return

    const liked = !isLiked(id)
    // write a 0 tombstone rather than deleting on un-like, so the un-like
    // syncs to devices that merge a cached copy of the likes (deleted keys are
    // indistinguishable from never-liked). the offset matches the native app
    const ts = liked ? 1696155367 + Date.now() : 0

    likes.value = { ...likes.value, [id]: ts }
    await db.put(`users/${uid}/likes/${id}`, ts)

    const countPath = `releases/${id}/likes/count`
    const count     = (await db.get<number>(countPath)) || 0
    await db.put(countPath, Math.max(0, count + (liked ? 1 : -1)))
  }

  return { likes, isLiked, loadLikes, toggleLike }
}
