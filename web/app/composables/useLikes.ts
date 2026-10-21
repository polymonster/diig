import { useFirebaseAuth } from 'vuefire'

// Module-level singletons, like usePlayer: one set of likes for the whole app,
// so a like from the player shows on the tiles and the other way round

const likes = ref<Record<string, number>>({})  // id -> timestamp, 0 is an un-like

// the load in flight or done for the signed in user, so app.vue and a page
// asking at the same time share one request
let loading: Promise<void> | null = null
let loadedUid: string | null = null

export function useLikes() {
  const auth = useFirebaseAuth()

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
      const token = await auth!.currentUser!.getIdToken()
      const data  = await fetch(`${DB}/users/${uid}/likes.json?auth=${token}`).then(r => r.json())
      likes.value = data && typeof data === 'object' ? data : {}
    })()
    return loading
  }

  async function toggleLike(release: any, e?: Event) {
    e?.stopPropagation()
    if (!auth?.currentUser || !release?.id) return
    const uid      = auth.currentUser.uid
    const id       = release.id
    const token    = await auth.currentUser.getIdToken()
    const countUrl = `${DB}/releases/${id}/likes/count.json?auth=${token}`

    const json = (body: any) => ({ method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

    if (isLiked(id)) {
      // write a 0 tombstone rather than deleting, so the un-like syncs to
      // devices that merge a cached copy of the likes (deleted keys are
      // indistinguishable from never-liked)
      likes.value = { ...likes.value, [id]: 0 }
      await fetch(`${DB}/users/${uid}/likes/${id}.json?auth=${token}`, json(0))
      const cur = await fetch(countUrl).then(r => r.json()) || 0
      await fetch(countUrl, json(Math.max(0, cur - 1)))
    } else {
      const ts = 1696155367 + Date.now()
      likes.value = { ...likes.value, [id]: ts }
      await fetch(`${DB}/users/${uid}/likes/${id}.json?auth=${token}`, json(ts))
      const cur = await fetch(countUrl).then(r => r.json()) || 0
      await fetch(countUrl, json(cur + 1))
    }
  }

  return { likes, isLiked, loadLikes, toggleLike }
}
