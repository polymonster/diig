<script setup lang="ts">
import { useCurrentUser } from 'vuefire'
import type { Release } from '~/utils/release'

// One store in depth: pick the store and view, toggle its sections. Releases
// render 30 at a time as the page scrolls

const user  = useCurrentUser()
const route = useRoute()
const { stores, loadStores, sectionIds, loadReleases } = useStores()
const { releaseList, stopAll } = usePlayer()

const LIST_SIZE = 150   // releases fetched per section
const PAGE_SIZE = 30    // releases rendered per scroll step

const selectedStoreId = ref('')
const selectedViewId  = ref('new_releases')
const enabledSections = ref(new Set<string>())

const selectedStore = computed(() => stores.value.find(s => s.id === selectedStoreId.value))
const isSectionless = computed(() => !!selectedStore.value?.views.find(v => v.id === selectedViewId.value)?.sectionless)

// ── Per store preferences ────────────────────────────────────────────────────

// the view and sections last picked for each store, browser only
interface StorePrefs { view: string, sections: string[] }

function loadPrefs(storeId: string): StorePrefs | null {
  return storageGetJson<Record<string, StorePrefs>>('diig_store_prefs', {})[storeId] ?? null
}

function savePrefs() {
  if (!selectedStoreId.value) return
  const all = storageGetJson<Record<string, StorePrefs>>('diig_store_prefs', {})
  all[selectedStoreId.value] = { view: selectedViewId.value, sections: [...enabledSections.value] }
  storageSet('diig_store_prefs', all)
}

function toggleSection(secId: string) {
  const next = new Set(enabledSections.value)
  if (next.has(secId)) next.delete(secId)
  else next.add(secId)
  enabledSections.value = next
  savePrefs()
}

// ── Releases ─────────────────────────────────────────────────────────────────

const sectionReleases = ref<Record<string, Release[]>>({})   // section id -> releases
const loading         = ref(false)
const visibleCount    = ref(PAGE_SIZE)

async function loadAll() {
  const store = selectedStore.value
  if (!store) return
  stopAll()
  loading.value         = true
  visibleCount.value    = PAGE_SIZE
  sectionReleases.value = {}
  const viewId = selectedViewId.value
  const ids    = sectionIds(store, viewId)
  const lists  = await Promise.all(ids.map(sec => loadReleases(store.id, sec, viewId, LIST_SIZE)))
  sectionReleases.value = Object.fromEntries(ids.map((sec, i) => [sec, lists[i]!]))
  loading.value = false
}

// the enabled sections merged, in section order
const releases = computed(() => {
  const store = selectedStore.value
  if (!store) return []
  if (isSectionless.value) return sectionReleases.value.sectionless ?? []
  return uniqueById(store.sections
    .filter(sec => enabledSections.value.has(sec.id))
    .map(sec => sectionReleases.value[sec.id] ?? []))
})

const visibleReleases = computed(() => releases.value.slice(0, visibleCount.value))

watch(releases, val => { releaseList.value = val })

// ── Infinite scroll ──────────────────────────────────────────────────────────

const sentinel = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null

onMounted(() => {
  observer = new IntersectionObserver(entries => {
    if (entries[0]?.isIntersecting) visibleCount.value += PAGE_SIZE
  }, { rootMargin: '200px' })
})
watch(sentinel, el => {
  observer?.disconnect()
  if (el) observer?.observe(el)
})
onUnmounted(() => observer?.disconnect())

// ── Selection ────────────────────────────────────────────────────────────────

watch(selectedStoreId, () => {
  const store = selectedStore.value
  if (!store) return
  storageSet('diig_last_store', store.id)
  const prefs = loadPrefs(store.id)
  enabledSections.value = new Set(prefs?.sections?.length ? prefs.sections : store.sections.map(s => s.id))
  const view = prefs?.view && store.views.some(v => v.id === prefs.view)
    ? prefs.view
    : store.views[0]?.id || 'new_releases'
  // a changed view triggers the load from the watch below
  if (view !== selectedViewId.value) selectedViewId.value = view
  else loadAll()
})

watch(selectedViewId, () => {
  loadAll()
  savePrefs()
})

watch(user, async u => {
  if (!u) return
  await loadStores()
  // deep link (?store=juno) wins, then the last visited, then the first store
  const has    = (id: unknown) => typeof id === 'string' && stores.value.some(s => s.id === id)
  const wanted = route.query.store
  const last   = storageGet('diig_last_store')
  selectedStoreId.value = has(wanted) ? wanted as string
    : has(last) ? last
    : stores.value[0]?.id ?? ''
}, { immediate: true })
</script>

<template>
  <div class="page">
    <AppHeader>
      <div class="controls">
        <select v-model="selectedStoreId" class="select">
          <option v-for="s in stores" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
        <select v-model="selectedViewId" class="select">
          <option v-for="v in selectedStore?.views ?? []" :key="v.id" :value="v.id">{{ v.label }}</option>
        </select>
        <NuxtLink to="/discogs" class="viewbtn">Discogs &rsaquo;</NuxtLink>
      </div>
    </AppHeader>

    <div v-if="!isSectionless && selectedStore?.sections.length" class="filter-bar sections">
      <button
        v-for="sec in selectedStore.sections"
        :key="sec.id"
        class="sec-btn"
        :class="{ active: enabledSections.has(sec.id) }"
        @click="toggleSection(sec.id)"
      >{{ sec.name }}</button>
    </div>

    <LoadingSpinner v-if="loading" full />

    <main v-else class="content">
      <p v-if="!visibleReleases.length" class="empty">no releases</p>
      <div v-else class="shelf">
        <ReleaseTile v-for="release in visibleReleases" :key="release.id" :release="release" />
      </div>
      <div ref="sentinel" class="sentinel" />
    </main>
  </div>
</template>

<style scoped>
.controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.select {
  font-size: 0.75rem;
  color: #333;
  background: #fff;
  border: 1px solid #ddd;
  border-radius: 3px;
  padding: 0.3rem 1.5rem 0.3rem 0.5rem;
  cursor: pointer;
  outline: none;
  appearance: none;
  /* a small down arrow */
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23aaa'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 0.45rem center;
  background-size: 8px;
}
.select:focus { border-color: #aaa; }

/* sticks under the header */
.sections {
  gap: 6px;
  position: sticky;
  top: 57px;
  z-index: 9;
}

.sec-btn {
  font-size: 0.62rem;
  padding: 0.25rem 0.6rem;
  border: 1px solid #ddd;
  border-radius: 2px;
  background: #fff;
  color: #aaa;
  cursor: pointer;
  transition: all 0.12s;
  letter-spacing: 0.02em;
}
.sec-btn:hover  { color: #333; border-color: #bbb; }
.sec-btn.active { background: var(--ink); color: #fff; border-color: var(--ink); }

.sentinel { height: 1px; }
</style>
