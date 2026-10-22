<script setup>
import { useFirebaseAuth, useCurrentUser } from 'vuefire'

const auth = useFirebaseAuth()
const user = useCurrentUser()

const stores = ref([])

async function fetchStores() {
  if (!auth.currentUser) return
  const token = await auth.currentUser.getIdToken()
  const data  = await fetch(`${DB}/stores.json?auth=${token}`).then(r => r.json())
  if (!data || typeof data !== 'object') return
  stores.value = Object.entries(data).map(([id, d]) => {
    const chartView = (d.view_order || [])[1] || 'weekly_chart'
    return {
      id,
      name:             d.display_name || id,
      artIndex:         d.art_index || 0,
      chartView,
      sectionlessChart: !!(d.views?.[chartView]?.sectionless),
      sections:         (d.sections || []).map((secId, i) => ({
        id:   secId,
        name: (d.section_display_names || [])[i] || secId,
      })),
    }
  })
}

const VIEWS = [
  { id: 'new_releases', label: 'New' },
  { id: 'chart',        label: 'Hot' },
]

const selectedView   = ref(localStorage.getItem('diig_view') || 'new_releases')
const sectionReleases = ref({})
const loading        = ref(false)

// bumped on each loadAll so superseded (e.g. view-switch) fetches don't write
let loadToken = 0

function sectionKey(storeId, sectionId) {
  return `${storeId}__${sectionId}`
}

function triplet(store, section, viewId) {
  if (viewId === 'chart' && store.sectionlessChart) return `${store.id}-sectionless-${store.chartView}`
  const v = viewId === 'chart' ? store.chartView : viewId
  return `${store.id}-${section.id}-${v}`
}

async function loadSection(store, section, viewId, runToken) {
  const key = sectionKey(store.id, section.id)
  const t   = triplet(store, section, viewId)
  try {
    const token = await auth.currentUser.getIdToken()
    const url   = `${DB}/releases.json?orderBy="${t}"&startAt=0&auth=${token}`
    const data  = await fetch(url).then(r => r.json())
    if (runToken !== loadToken) return // a newer load superseded this one; don't write stale data
    if (!data || typeof data !== 'object') { sectionReleases.value[key] = []; return }
    const items = Object.entries(data).map(([id, v]) => ({ ...v, id }))
    items.sort((a, b) => (a[t] ?? 999) - (b[t] ?? 999))
    sectionReleases.value[key] = items.slice(0, 32)
  } catch (e) {
    console.error(t, e)
    if (runToken === loadToken) sectionReleases.value[key] = []
  }
}

async function loadAll() {
  const myToken = ++loadToken // supersede any in-flight sequential load
  loading.value = true
  const blank = {}
  for (const s of stores.value) for (const sec of s.sections) blank[sectionKey(s.id, sec.id)] = []
  sectionReleases.value = blank
  // load store by store in display order: each store's sections are fetched
  // together, but stores fill in top-down so the first appears without waiting
  // on the rest. releasesByStore updates reactively as each store lands
  for (const s of sortedStores.value) {
    if (myToken !== loadToken) return // a newer load (e.g. view switch) took over
    await Promise.all(s.sections.map(sec => loadSection(s, sec, selectedView.value, myToken)))
  }
  if (myToken === loadToken) loading.value = false
}

watch(user, async u => { if (u) { await fetchStores(); loadStoreOrder(); loadAll() } }, { immediate: true })

function selectView(viewId) {
  stopAll()
  selectedView.value = viewId
  localStorage.setItem('diig_view', viewId)
  loadAll()
}


// ── Store ordering ───────────────────────────────────────────────────────────

// seed from the cached order synchronously so the feed loads top-down in the
// right order without waiting on the account copy (loadStoreOrder refines it)
function readStoredOrder() {
  try { const v = JSON.parse(localStorage.getItem('diig_store_order') || '[]'); return Array.isArray(v) ? v : [] }
  catch { return [] }
}
const storeOrder = ref(readStoredOrder())  // array of store ids, user preferred order

// stores sorted by the user's preferred order; unknown (new) stores keep their
// default position at the end
const sortedStores = computed(() => {
  const order = storeOrder.value
  return [...stores.value].sort((a, b) => {
    const ia = order.indexOf(a.id)
    const ib = order.indexOf(b.id)
    return (ia === -1 ? order.length : ia) - (ib === -1 ? order.length : ib)
  })
})

async function loadStoreOrder() {
  // account copy wins so the order follows the user across devices,
  // localStorage is the fallback
  try {
    if (auth.currentUser) {
      const token = await auth.currentUser.getIdToken()
      const data  = await fetch(`${DB}/users/${auth.currentUser.uid}/web_prefs/store_order.json?auth=${token}`).then(r => r.json())
      if (Array.isArray(data) && data.length) {
        storeOrder.value = data
        localStorage.setItem('diig_store_order', JSON.stringify(data))
        return
      }
    }
  } catch { /* fall back to local */ }
  try {
    const local = JSON.parse(localStorage.getItem('diig_store_order') || '[]')
    if (Array.isArray(local)) storeOrder.value = local
  } catch { /* default order */ }
}

async function saveStoreOrder() {
  localStorage.setItem('diig_store_order', JSON.stringify(storeOrder.value))
  if (!auth.currentUser) return
  try {
    const token = await auth.currentUser.getIdToken()
    await fetch(`${DB}/users/${auth.currentUser.uid}/web_prefs/store_order.json?auth=${token}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(storeOrder.value),
    })
  } catch (e) { console.error('store order save', e) }
}

const releasesByStore = computed(() =>
  sortedStores.value.map(store => {
    const seen     = new Set()
    const releases = []
    for (const sec of store.sections) {
      for (const r of sectionReleases.value[sectionKey(store.id, sec.id)] || []) {
        if (!seen.has(r.id)) { seen.add(r.id); releases.push(r) }
      }
    }
    return { store, releases: releases.slice(0, 32) }
  }).filter(s => s.releases.length)
)

// swap a store block with its visible neighbour and persist the full order
function moveStore(storeId, dir) {
  const visible = releasesByStore.value.map(x => x.store.id)
  const i = visible.indexOf(storeId)
  const j = i + dir
  if (i === -1 || j < 0 || j >= visible.length) return
  ;[visible[i], visible[j]] = [visible[j], visible[i]]
  const rest = sortedStores.value.map(s => s.id).filter(id => !visible.includes(id))
  storeOrder.value = [...visible, ...rest]
  saveStoreOrder()
}

// ── Auto-play on scroll (mobile) ─────────────────────────────────────────────

const flatReleases = computed(() => releasesByStore.value.flatMap(({ releases }) => releases))

let scrollRaf = null

function centeredReleaseId() {
  const cy = window.innerHeight / 2
  let bestId = null
  let bestDist = Infinity
  document.querySelectorAll('[data-release-id]').forEach(el => {
    const r = el.getBoundingClientRect()
    const dist = Math.abs((r.top + r.height / 2) - cy)
    if (dist < bestDist) { bestDist = dist; bestId = el.dataset.releaseId }
  })
  return bestId
}

function onScrollPlay() {
  if (window.innerWidth > 600) return
  // only auto-advance while something is already playing (audio unlocked by user)
  if (!isPlaying.value) return
  if (scrollRaf) return
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = null
    const id = centeredReleaseId()
    if (!id || activeId.value === id) return
    const release = flatReleases.value.find(r => r.id === id)
    if (release && getTracks(release).length) tileClick(release)
  })
}

onMounted(() => { if (import.meta.client) window.addEventListener('scroll', onScrollPlay, { passive: true }) })
onUnmounted(() => { if (import.meta.client) window.removeEventListener('scroll', onScrollPlay) })

// ── Player ────────────────────────────────────────────────────────────────────

const menuOpen = useState('menuOpen', () => false)
const { isLive } = useLiveStatus()

const { activeId, isPlaying, releaseList, tileClickAudio: tileClick, getTracks, stopAll } = usePlayer()

watch(releasesByStore, val => {
  releaseList.value = val.flatMap(({ releases }) => releases)
})
</script>

<template>
  <div class="page">
    <header class="header">
      <span class="logo">diig</span>
      <nav class="viewnav">
        <button
          v-for="v in VIEWS"
          :key="v.id"
          class="viewbtn"
          :class="{ active: selectedView === v.id }"
          @click="selectView(v.id)"
        >{{ v.label }}</button>
        <NuxtLink to="/weekly"  class="viewbtn stores-link">Weekly &rsaquo;</NuxtLink>
        <NuxtLink to="/stores"  class="viewbtn stores-link">Stores &rsaquo;</NuxtLink>
        <NuxtLink to="/discogs" class="viewbtn stores-link">Discogs &rsaquo;</NuxtLink>
      </nav>
      <div class="header-right">
        <NuxtLink v-if="isLive" to="/live" class="live-nav">
          <span class="live-nav-dot" />live
        </NuxtLink>
        <NuxtLink to="/likes" class="likes-nav">
          <span class="fa">&#xf004;</span>
        </NuxtLink>
        <button class="burger-btn fa" @click="menuOpen = !menuOpen">&#xf0c9;</button>
      </div>
    </header>

    <div v-if="loading && !releasesByStore.length" class="loading">
      <img src="/spinner.png" class="spinner" alt="loading" />
    </div>

    <main v-else class="content">
      <div v-for="({ store, releases }, si) in releasesByStore" :key="store.id" class="store-block">
        <h2 class="store-name">
          <NuxtLink :to="`/stores?store=${store.id}`" class="store-link">{{ store.name }}</NuxtLink>
          <span class="order-btns">
            <button class="order-btn fa" :disabled="si === 0" title="Move up" @click="moveStore(store.id, -1)">&#xf077;</button>
            <button class="order-btn fa" :disabled="si === releasesByStore.length - 1" title="Move down" @click="moveStore(store.id, 1)">&#xf078;</button>
          </span>
        </h2>
        <div class="tile-row">
          <ReleaseTile v-for="release in releases" :key="release.id" :release="release" />
        </div>
      </div>

      <div v-if="loading && releasesByStore.length" class="loading-more">
        <img src="/spinner.png" class="spinner-sm" alt="loading more" />
      </div>
    </main>
  </div>
</template>

<style scoped>
@font-face {
  font-family: 'Cousine';
  src: url('/cousine-regular.ttf') format('truetype');
}

@font-face {
  font-family: 'FontAwesome';
  src: url('/fontawesome-webfont.ttf') format('truetype');
  font-weight: normal;
  font-style: normal;
}

* { font-family: 'Cousine', monospace; box-sizing: border-box; }

.fa {
  font-family: 'FontAwesome';
  font-style: normal;
  font-weight: normal;
  line-height: 1;
  -webkit-font-smoothing: antialiased;
}

.page {
  min-height: 100vh;
  background: #f5f5f5;
  color: #0a0a0a;
  padding-bottom: 64px;
}

.header {
  display: flex;
  align-items: center;
  gap: 2rem;
  padding: 1rem 1.5rem;
  background: #fff;
  border-bottom: 1px solid #e0e0e0;
  position: sticky;
  top: 0;
  z-index: 10;
}

.logo {
  font-size: 1.1rem;
  letter-spacing: 0.1em;
}

.viewnav {
  display: flex;
  gap: 0.25rem;
}

.viewbtn {
  padding: 0.35rem 0.9rem;
  font-family: 'Cousine', monospace;
  font-size: 0.8rem;
  background: none;
  border: 1px solid transparent;
  color: #999;
  cursor: pointer;
  transition: all 0.15s;
}

.viewbtn:hover  { color: #333; }
.viewbtn.active { border-color: #0a0a0a; color: #0a0a0a; }

.stores-link { text-decoration: none; white-space: nowrap; }

.header-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.9rem;
}

.likes-nav {
  font-size: 1rem;
  color: #ccc;
  text-decoration: none;
  transition: color 0.15s;
}
.likes-nav:hover { color: #e03070; }

.loading {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 60vh;
}

.spinner {
  width: 80px;
  height: 80px;
  animation: spin 1.2s linear infinite;
}

.loading-more {
  display: flex;
  justify-content: center;
  padding: 1rem 0 2rem;
}

.spinner-sm {
  width: 36px;
  height: 36px;
  animation: spin 1.2s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

.content {
  max-width: 1400px;
  margin: 0 auto;
  padding: 1.5rem;
}

.store-block {
  display: grid;
  grid-template-columns: repeat(auto-fill, 150px);
  gap: 8px;
  justify-content: center;
  margin-bottom: 2rem;
}

.store-name {
  grid-column: 1 / -1;
  font-size: 0.7rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  margin: 0 0 0.25rem;
}

.store-link {
  color: #999;
  text-decoration: none;
  transition: color 0.15s;
}
.store-link:hover { color: #0a0a0a; }

.order-btns {
  margin-left: 0.6rem;
  display: inline-flex;
  gap: 0.4rem;
}

.order-btn {
  background: none;
  border: none;
  padding: 0;
  font-size: 0.6rem;
  color: #ccc;
  cursor: pointer;
  transition: color 0.15s;
}
.order-btn:hover:not(:disabled) { color: #0a0a0a; }
.order-btn:disabled { opacity: 0.25; cursor: default; }

.tile-row {
  display: contents;
}

@media (max-width: 600px) {
  /* header: row 1 = logo + icons, row 2 = nav */
  .header {
    flex-wrap: wrap;
    gap: 0;
    padding: 0.75rem 1rem 0;
  }
  .header-right { margin-left: auto; }
  .viewnav {
    order: 3;
    width: 100%;
    padding: 0.35rem 0 0.35rem;
    border-top: 1px solid #f0f0f0;
    margin-top: 0.5rem;
    gap: 0;
  }
  .viewnav .viewbtn { flex: 1; text-align: center; padding: 0.3rem 0.4rem; }

  /* tiles */
  .store-block { grid-template-columns: 1fr; }
}

.empty {
  font-size: 0.75rem;
  color: #bbb;
  padding: 0.5rem 0;
  margin: 0;
}
</style>
