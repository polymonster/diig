<script setup>
import { useFirebaseAuth, useCurrentUser } from 'vuefire'

const auth = useFirebaseAuth()
const user = useCurrentUser()
const DB   = 'https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app'

const VIEW_PRIORITY = ['new_releases', 'weekly_chart', 'monthly_chart']

// ── Store data (fetched from Firebase) ────────────────────────────────────────

const rawStores      = ref({})
const selectedStoreId = ref('')
const selectedViewId  = ref('new_releases')
const enabledSections = ref(new Set())

const storeList = computed(() => {
  return Object.keys(rawStores.value)
    .map(id => {
      const d   = rawStores.value[id]
      const vs  = d.views || {}
      const ord = d.view_order || VIEW_PRIORITY
      const priority = ord.filter(v => vs[v])
      const rest     = Object.keys(vs).filter(v => !ord.includes(v))
      return {
        id,
        name:     id.charAt(0).toUpperCase() + id.slice(1),
        artIndex: d.art_index || 0,
        views: [...priority, ...rest].map(v => ({
          id:         v,
          label:      vs[v].display_name || v,
          sectionless: !!vs[v].sectionless,
        })),
        sections: (d.sections || []).map((secId, i) => ({
          id:   secId,
          name: (d.section_display_names || [])[i] || secId,
        })),
      }
    })
})

const selectedStore   = computed(() => storeList.value.find(s => s.id === selectedStoreId.value))
const currentView     = computed(() => selectedStore.value?.views.find(v => v.id === selectedViewId.value))
const isSectionless   = computed(() => currentView.value?.sectionless ?? false)

// ── Release loading ───────────────────────────────────────────────────────────

const sectionReleases = ref({})
const loading         = ref(false)

function sectionKey(storeId, sectionId) { return `${storeId}__${sectionId}` }

async function loadSection(store, sectionId, viewId) {
  const key = sectionKey(store.id, sectionId)
  const t   = `${store.id}-${sectionId}-${viewId}`
  try {
    const token = await auth.currentUser.getIdToken()
    const url   = `${DB}/releases.json?orderBy="${t}"&startAt=0&auth=${token}`
    const data  = await fetch(url).then(r => r.json())
    if (!data || typeof data !== 'object') { sectionReleases.value[key] = []; return }
    const items = Object.entries(data).map(([id, v]) => ({ id, ...v }))
    items.sort((a, b) => (a[t] ?? 999) - (b[t] ?? 999))
    sectionReleases.value[key] = items.slice(0, 40)
  } catch (e) {
    console.error(t, e)
    sectionReleases.value[key] = []
  }
}

async function loadAll() {
  const store = selectedStore.value
  if (!store || !auth.currentUser) return
  stopAll()
  loading.value = true
  const viewId     = selectedViewId.value
  const sectionIds = isSectionless.value ? ['sectionless'] : store.sections.map(s => s.id)
  const blank      = {}
  for (const s of sectionIds) blank[sectionKey(store.id, s)] = []
  sectionReleases.value = blank
  await Promise.all(sectionIds.map(s => loadSection(store, s, viewId)))
  loading.value = false
}

const aggregatedReleases = computed(() => {
  const store = selectedStore.value
  if (!store) return []
  if (isSectionless.value) return sectionReleases.value[sectionKey(store.id, 'sectionless')] || []
  const seen = new Set()
  const out  = []
  for (const sec of store.sections) {
    if (!enabledSections.value.has(sec.id)) continue
    for (const r of sectionReleases.value[sectionKey(store.id, sec.id)] || []) {
      if (!seen.has(r.id)) { seen.add(r.id); out.push(r) }
    }
  }
  return out.slice(0, 120)
})

function toggleSection(secId) {
  const next = new Set(enabledSections.value)
  if (next.has(secId)) next.delete(secId)
  else next.add(secId)
  enabledSections.value = next
}

watch(selectedStoreId, () => {
  const store = selectedStore.value
  if (!store) return
  enabledSections.value = new Set(store.sections.map(s => s.id))
  selectedViewId.value  = store.views[0]?.id || 'new_releases'
  loadAll()
})

watch(selectedViewId, () => {
  if (storeList.value.length) loadAll()
})

async function fetchStores() {
  if (!auth.currentUser) return
  const token = await auth.currentUser.getIdToken()
  const data  = await fetch(`${DB}/stores.json?auth=${token}`).then(r => r.json())
  if (!data || typeof data !== 'object') return
  rawStores.value = data
  if (!selectedStoreId.value) selectedStoreId.value = Object.keys(data)[0] ?? ''
  const store = selectedStore.value
  if (store) enabledSections.value = new Set(store.sections.map(s => s.id))
  await loadAll()
}

watch(user, u => { if (u) { fetchStores(); loadLikes() } }, { immediate: true })

// ── Likes ─────────────────────────────────────────────────────────────────────

const likes           = ref({})
const likeCountAdjust = ref({})

function isLiked(id) { return id in likes.value }

async function loadLikes() {
  if (!auth.currentUser) return
  const uid   = auth.currentUser.uid
  const token = await auth.currentUser.getIdToken()
  const data  = await fetch(`${DB}/users/${uid}/likes.json?auth=${token}`).then(r => r.json())
  if (data && typeof data === 'object') likes.value = data
}

async function toggleLike(release, e) {
  e.stopPropagation()
  if (!auth.currentUser) return
  const uid      = auth.currentUser.uid
  const id       = release.id
  const token    = await auth.currentUser.getIdToken()
  const countUrl = `${DB}/releases/${id}/likes/count.json?auth=${token}`

  if (isLiked(id)) {
    const { [id]: _, ...rest } = likes.value
    likes.value = rest
    likeCountAdjust.value = { ...likeCountAdjust.value, [id]: (likeCountAdjust.value[id] ?? 0) - 1 }
    await fetch(`${DB}/users/${uid}/likes/${id}.json?auth=${token}`, { method: 'DELETE' })
    const cur = await fetch(countUrl).then(r => r.json()) || 0
    await fetch(countUrl, { method: 'PUT', body: JSON.stringify(Math.max(0, cur - 1)) })
  } else {
    const ts = Date.now() / 1000
    likes.value = { ...likes.value, [id]: ts }
    likeCountAdjust.value = { ...likeCountAdjust.value, [id]: (likeCountAdjust.value[id] ?? 0) + 1 }
    await fetch(`${DB}/users/${uid}/likes/${id}.json?auth=${token}`, { method: 'PUT', body: JSON.stringify(ts) })
    const cur = await fetch(countUrl).then(r => r.json()) || 0
    await fetch(countUrl, { method: 'PUT', body: JSON.stringify(cur + 1) })
  }
}

function tags(release) { return release.store_tags || {} }

// ── Player ────────────────────────────────────────────────────────────────────

const menuOpen = useState('menuOpen', () => false)

const { activeId, activeTrack, isPlaying, releaseList, tileClick, prevTrack, nextTrack, dotClick, computeDots, getTracks, getTrackNames, stopAll } = useAudio()

watch(aggregatedReleases, val => { releaseList.value = val })
</script>

<template>
  <div class="page">
    <header class="header">
      <NuxtLink to="/" class="logo">diig</NuxtLink>

      <div class="controls">
        <select v-model="selectedStoreId" class="store-select">
          <option v-for="s in storeList" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
        <select v-model="selectedViewId" class="view-select">
          <option v-for="v in (selectedStore?.views ?? [])" :key="v.id" :value="v.id">{{ v.label }}</option>
        </select>
      </div>

      <div class="header-right">
        <NuxtLink to="/likes" class="likes-nav">
          <span class="fa">&#xf004;</span>
        </NuxtLink>
        <button class="burger-btn fa" @click="menuOpen = !menuOpen">&#xf0c9;</button>
      </div>
    </header>

    <div v-if="!isSectionless && selectedStore?.sections.length" class="filter-bar">
      <button
        v-for="sec in selectedStore.sections"
        :key="sec.id"
        class="sec-btn"
        :class="{ active: enabledSections.has(sec.id) }"
        @click="toggleSection(sec.id)"
      >{{ sec.name }}</button>
    </div>

    <div v-if="loading" class="loading">
      <img src="/spinner.png" class="spinner" alt="loading" />
    </div>

    <main v-else class="content">
      <p v-if="!aggregatedReleases.length" class="empty">no releases</p>

      <div v-else class="tile-row">
        <div
          v-for="release in aggregatedReleases"
          :key="release.id"
          class="tile"
          :class="{ active: activeId === release.id, 'no-audio': !getTracks(release).length }"
          @click="getTracks(release).length && tileClick(release)"
        >
          <p v-if="release.cat" class="r-cat">{{ release.cat }}</p>
          <img
            :src="artworkUrl(release) || '/white_label.jpg'"
            :alt="release.title"
            class="tile-art"
            @error="e => e.target.src = '/white_label.jpg'"
          />
          <p class="r-artist">{{ release.artist }}</p>
          <p class="r-title">{{ release.title || ' ' }}</p>

          <div class="icons-row">
            <div class="icons-left">
              <button class="icon-btn like-btn" :class="{ liked: isLiked(release.id) }" @click="toggleLike(release, $event)">
                <span v-if="isLiked(release.id)" class="fa">&#xf004;</span><span v-else class="fa">&#xf08a;</span>
              </button>
              <a
                v-if="release.link"
                :href="release.link"
                target="_blank"
                class="icon-btn buy-btn"
                :class="{ preorder: tags(release).preorder, sold: tags(release).out_of_stock }"
                @click.stop
              >
                <span v-if="tags(release).preorder" class="fa">&#xf271;</span><span v-else class="fa">&#xf07a;</span>
              </a>
            </div>
            <div class="hype-icons">
              <span v-if="tags(release).has_charted"                                          class="fa hype fire"   title="Charted">&#xf06d;</span>
              <span v-if="tags(release).low_stock"                                            class="fa hype thermo" title="Low stock">&#xf2ca;</span>
              <span v-if="tags(release).has_been_out_of_stock && !tags(release).out_of_stock" class="fa hype excl"   title="Back in stock">&#xf12a;</span>
            </div>
          </div>

          <div v-if="getTracks(release).length" class="dots-row">
            <button
              v-if="activeId === release.id && getTracks(release).length > 1"
              class="nav-btn"
              :disabled="activeTrack === 0"
              @click="prevTrack(release, $event)"
            >&#8249;</button>

            <template v-for="dots in [computeDots(getTracks(release).length, activeId === release.id ? activeTrack : -1)]" :key="0">
            <svg :width="dots.length * 12" height="12">
              <g
                v-for="(dot, i) in dots"
                :key="i"
                style="cursor:pointer"
                @click="dotClick(release, dot, $event)"
              >
                <circle v-if="dot.small" :cx="i*12+6" cy="6" r="1.5" fill="#bbb" opacity="0.4" />
                <template v-else-if="dot.selected && isPlaying">
                  <polygon :points="`${i*12+4},3 ${i*12+4},9 ${i*12+9},6`" fill="#cc4d00" />
                </template>
                <circle v-else-if="dot.selected" :cx="i*12+6" cy="6" r="3.5" fill="#cc4d00" />
                <circle v-else
                  :cx="i*12+6" cy="6" r="2.5"
                  :fill="activeId === release.id ? '#999' : '#ccc'"
                  :opacity="activeId === release.id ? 1 : 0.35"
                />
              </g>
            </svg>
            </template>

            <button
              v-if="activeId === release.id && getTracks(release).length > 1"
              class="nav-btn"
              :disabled="activeTrack === getTracks(release).length - 1"
              @click="nextTrack(release, $event)"
            >&#8250;</button>
          </div>
          <div v-else class="dots-row no-audio-row">
            <span class="no-audio-label">no audio</span>
          </div>

          <div v-if="activeId === release.id" class="r-trackname-wrap">
            <span class="r-trackname" :key="`${release.id}-${activeTrack}`">{{ getTrackNames(release)[activeTrack] || '' }}</span>
          </div>
        </div>
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

.page { min-height: 100vh; background: #f5f5f5; color: #0a0a0a; }

.header {
  display: flex;
  align-items: center;
  gap: 1.25rem;
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
  text-decoration: none;
  color: #0a0a0a;
}

.controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.store-select,
.view-select {
  font-family: 'Cousine', monospace;
  font-size: 0.75rem;
  color: #333;
  background: #fff;
  border: 1px solid #ddd;
  border-radius: 3px;
  padding: 0.3rem 1.5rem 0.3rem 0.5rem;
  cursor: pointer;
  outline: none;
  appearance: none;
  -webkit-appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23aaa'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 0.45rem center;
  background-size: 8px;
}

.store-select:focus,
.view-select:focus { border-color: #aaa; }

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

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0.6rem 1.5rem;
  background: #fff;
  border-bottom: 1px solid #e0e0e0;
  position: sticky;
  top: 57px;
  z-index: 9;
}

.sec-btn {
  font-family: 'Cousine', monospace;
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
.sec-btn.active { background: #0a0a0a; color: #fff; border-color: #0a0a0a; }

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

@keyframes spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

.content {
  max-width: 1400px;
  margin: 0 auto;
  padding: 1.5rem;
}

.tile-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tile      { width: 120px; flex: 0 0 120px; cursor: pointer; }
.tile.no-audio { cursor: default; }

.tile-art  { width: 120px; height: 120px; object-fit: cover; display: block; }

.r-cat {
  font-size: 0.55rem; color: #bbb;
  margin: 0 0 2px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

.r-artist {
  font-size: 0.65rem; color: #0a0a0a;
  margin: 3px 0 1px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

.r-title {
  font-size: 0.6rem; color: #888;
  margin: 0;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  min-height: 1em;
}

.r-trackname-wrap {
  overflow: hidden;
  text-align: center;
  margin-top: 3px;
}

.r-trackname {
  display: inline-block;
  font-size: 0.58rem;
  color: #cc4d00;
  white-space: nowrap;
  animation: trackscroll 7s ease-in-out infinite;
}

@keyframes trackscroll {
  0%,  20% { transform: translateX(0); }
  80%, 100% { transform: translateX(min(0px, calc(120px - 100%))); }
}

.dots-row {
  display: flex; align-items: center; justify-content: center;
  gap: 3px; margin-top: 2px;
}

.no-audio-label { font-size: 0.5rem; color: #ddd; letter-spacing: 0.05em; }

.nav-btn {
  background: none; border: none;
  font-family: 'Cousine', monospace;
  font-size: 1rem; color: #aaa;
  cursor: pointer; padding: 0; line-height: 1;
  transition: color 0.1s;
}
.nav-btn:not(:disabled):hover { color: #333; }
.nav-btn:disabled { opacity: 0.25; cursor: default; }

.icons-row {
  display: flex; align-items: center; justify-content: space-between;
  margin-top: 4px; height: 16px;
}

.icons-left { display: flex; align-items: center; gap: 5px; }

.icon-btn {
  background: none; border: none; padding: 0; cursor: pointer;
  display: flex; align-items: center; gap: 2px;
  color: #bbb; font-size: 0.75rem; line-height: 1;
  transition: color 0.15s; text-decoration: none;
}

.like-btn:hover { color: #e03070; }
.like-btn.liked { color: #e03070; }

.buy-btn:hover    { color: #333; }
.buy-btn.preorder { color: #7a8a99; }
.buy-btn.sold     { color: #ccc; opacity: 0.4; }

.hype-icons { display: flex; align-items: center; gap: 3px; font-size: 0.7rem; }
.hype.fire   { color: #cc4d00; }
.hype.thermo { color: #e09000; }
.hype.excl   { color: #aaa; }

.empty { font-size: 0.75rem; color: #bbb; padding: 0.5rem 0; margin: 0; }
</style>
