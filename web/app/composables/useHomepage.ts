import { useFirebaseAuth } from 'vuefire'

// the weekly curated homepage, written to /homepage/current by scrape/homepage.py
const page    = ref<any | null>(null)
const loading = ref(false)

export function useHomepage() {
  const auth = useFirebaseAuth()

  async function loadHomepage() {
    if (!auth?.currentUser) return
    loading.value = true
    try {
      const token = await auth.currentUser.getIdToken()
      const data  = await fetch(`${DB}/homepage/current.json?auth=${token}`).then(r => r.json())
      page.value  = data && typeof data === 'object' && !data.error ? data : null
    } catch (e) {
      console.error('homepage', e)
      page.value = null
    } finally {
      loading.value = false
    }
  }

  return { page, loading, loadHomepage }
}
