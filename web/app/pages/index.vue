<script setup lang="ts">
import { useCurrentUser } from 'vuefire'
import type { Release } from '~/utils/release'
import type { Store } from '~/composables/useStores'

// Home: a shelf of the latest (New) or charting (Hot) releases from every
// store, in the user's preferred store order

const user = useCurrentUser()
const db   = useDb()
const { stores, loadStores, loadReleases } = useStores()
const { activeId, isPlaying, releaseList, getTracks, toggleRelease, stopAll } = usePlayer()

const SHELF_SIZE = 32

const VIEWS = [
  { id: 'new_releases', label: 'New' },
  { id: 'chart',        label: 'Hot' },
]

const selectedView  = ref(storageGet('diig_view', 'new_releases'))
const storeReleases = ref<Record<string, Release[]>>({})   // store id -> its shelf
const loading       = ref(false)

// ── Store ordering ───────────────────────────────────────────────────────────

// seeded from the cached order so the shelves load top-down in the right
// order straight away; loadStoreOrder refines it from the account copy
const storeOrder = ref<string[]>(storageGetJson('diig_store_order', []))

// the user's order, with stores they haven't placed (new ones) at the end
const sortedStores = computed(() => {
  const order = storeOrder.value
  const rank  = (id: string) => { const i = order.indexOf(id); return i === -1 ? order.length : i }
  return [...stores.value].sort((a, b) => rank(a.id) - rank(b.id))
})

// the account copy wins so the order follows the user across devices
async function loadStoreOrder() {
  const order = await db.get<string[]>(`users/${user.value?.uid}/web_prefs/store_order`)
  if (Array.isArray(order) && order.length) {
    storeOrder.value = order
    storageSet('diig_store_order', order)
  }
}

function saveStoreOrder() {
  storageSet('diig_store_order', storeOrder.value)
  if (user.value) db.put(`users/${user.value.uid}/web_prefs/store_order`, storeOrder.value)
}

// swap a store with its visible neighbour and persist the full order
function moveStore(storeId: string, dir: 1 | -1) {
  const visible = shelves.value.map(s => s.store.id)
  const i = visible.indexOf(storeId)
  const j = i + dir
  if (i === -1 || j < 0 || j >= visible.length) return
  ;[visible[i], visible[j]] = [visible[j]!, visible[i]!]
  const rest = sortedStores.value.map(s => s.id).filter(id => !visible.includes(id))
  storeOrder.value = [...visible, ...rest]
  saveStoreOrder()
}

// ── Loading ──────────────────────────────────────────────────────────────────

// bumped on each loadAll, so a superseded load (e.g. after a view switch)
// stops and doesn't write stale data
let loadGeneration = 0

// one store's shelf: every section of the view merged, best ranked first
async function loadShelf(store: Store, viewId: string): Promise<Release[]> {
  const view       = viewId === 'chart' ? store.chartView : viewId
  const sectionless = store.views.find(v => v.id === view)?.sectionless
  const sections   = sectionless ? ['sectionless'] : store.sections.map(s => s.id)
  const lists      = await Promise.all(sections.map(sec => loadReleases(store.id, sec, view, SHELF_SIZE)))
  return uniqueById(lists).slice(0, SHELF_SIZE)
}

// store by store in display order, so the first shelf shows without waiting
// on the rest
async function loadAll() {
  const gen = ++loadGeneration
  loading.value       = true
  storeReleases.value = {}
  for (const store of sortedStores.value) {
    const shelf = await loadShelf(store, selectedView.value)
    if (gen !== loadGeneration) return
    storeReleases.value = { ...storeReleases.value, [store.id]: shelf }
  }
  loading.value = false
}

watch(user, async u => {
  if (!u) return
  await Promise.all([loadStores(), loadStoreOrder()])
  loadAll()
}, { immediate: true })

function selectView(viewId: string) {
  stopAll()
  selectedView.value = viewId
  storageSet('diig_view', viewId)
  loadAll()
}

const shelves = computed(() =>
  sortedStores.value
    .map(store => ({ store, releases: storeReleases.value[store.id] ?? [] }))
    .filter(s => s.releases.length))

watch(shelves, val => { releaseList.value = val.flatMap(s => s.releases) })

// ── Auto-play on scroll (mobile) ─────────────────────────────────────────────

// while something is playing, scrolling a tile to the middle of the screen
// plays it
let scrollRaf = 0

function centredReleaseId(): string | null {
  const cy = window.innerHeight / 2
  let bestId: string | null = null
  let bestDist = Infinity
  document.querySelectorAll<HTMLElement>('[data-release-id]').forEach(el => {
    const r    = el.getBoundingClientRect()
    const dist = Math.abs(r.top + r.height / 2 - cy)
    if (dist < bestDist) { bestDist = dist; bestId = el.dataset.releaseId ?? null }
  })
  return bestId
}

function onScroll() {
  if (window.innerWidth > 600 || !isPlaying.value || scrollRaf) return
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = 0
    const id = centredReleaseId()
    if (!id || activeId.value === id) return
    const release = releaseList.value.find(r => r.id === id)
    if (release && getTracks(release).length) toggleRelease(release, 'audio')
  })
}

onMounted(() => window.addEventListener('scroll', onScroll, { passive: true }))
onUnmounted(() => window.removeEventListener('scroll', onScroll))
</script>

<template>
  <div class="page">
    <AppHeader>
      <nav class="viewnav">
        <button
          v-for="v in VIEWS"
          :key="v.id"
          class="viewbtn"
          :class="{ active: selectedView === v.id }"
          @click="selectView(v.id)"
        >{{ v.label }}</button>
        <NuxtLink to="/weekly"  class="viewbtn">Weekly &rsaquo;</NuxtLink>
        <NuxtLink to="/stores"  class="viewbtn">Stores &rsaquo;</NuxtLink>
        <NuxtLink to="/discogs" class="viewbtn">Discogs &rsaquo;</NuxtLink>
      </nav>
    </AppHeader>

    <LoadingSpinner v-if="loading && !shelves.length" full />

    <main v-else class="content">
      <div v-for="({ store, releases }, si) in shelves" :key="store.id" class="shelf store">
        <h2 class="shelf-name">
          <NuxtLink :to="`/stores?store=${store.id}`" class="store-link">{{ store.name }}</NuxtLink>
          <span class="order-btns">
            <button class="order-btn fa" :disabled="si === 0" title="Move up" @click="moveStore(store.id, -1)">{{ ICON.chevronUp }}</button>
            <button class="order-btn fa" :disabled="si === shelves.length - 1" title="Move down" @click="moveStore(store.id, 1)">{{ ICON.chevronDown }}</button>
          </span>
        </h2>
        <ReleaseTile v-for="release in releases" :key="release.id" :release="release" />
      </div>

      <LoadingSpinner v-if="loading" />
    </main>
  </div>
</template>

<style scoped>
.store { margin-bottom: 2rem; }

.store-link {
  color: inherit;
  text-decoration: none;
  transition: color 0.15s;
}
.store-link:hover { color: var(--ink); }

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
.order-btn:hover:not(:disabled) { color: var(--ink); }
.order-btn:disabled { opacity: 0.25; cursor: default; }
</style>
