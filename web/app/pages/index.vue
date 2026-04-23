<script setup>
import { useFirebaseAuth, useCurrentUser } from 'vuefire'

const auth = useFirebaseAuth()
const user = useCurrentUser()
const DB = 'https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app'

const STORES = [
  {
    id: 'redeye', name: 'Redeye', artIndex: 0, chartView: 'weekly_chart',
    sections: [
      { id: 'techno-electro', name: 'Techno / Electro' },
      { id: 'house-disco',    name: 'House / Disco' },
      { id: 'bass-music',     name: 'Bass Music' },
    ],
  },
  {
    id: 'juno', name: 'Juno', artIndex: 0, chartView: 'weekly_chart',
    sections: [
      { id: 'minimal-tech-house', name: 'Minimal / Tech House' },
      { id: 'deep-house',         name: 'Deep House' },
      { id: 'techno-music',       name: 'Techno' },
      { id: 'breakbeat',          name: 'Breakbeat' },
      { id: 'electro',            name: 'Electro' },
    ],
  },
  {
    id: 'phonica', name: 'Phonica', artIndex: 0, chartView: 'bestsellers',
    sections: [
      { id: 'tech-house', name: 'Tech House / Minimal' },
      { id: 'techno',     name: 'Techno / Electro' },
      { id: 'house',      name: 'House' },
    ],
  },
  {
    id: 'yoyaku', name: 'Yoyaku', artIndex: 1, chartView: 'weekly_chart',
    sections: [
      { id: 'breaks',     name: 'Breaks' },
      { id: 'dub-techno', name: 'Dub Techno' },
      { id: 'minimal',    name: 'Minimal' },
      { id: 'electro',    name: 'Electro' },
      { id: 'house',      name: 'House' },
    ],
  },
  {
    id: 'hardwax', name: 'Hardwax', artIndex: 1, chartView: 'this_week', sectionlessChart: true,
    sections: [
      { id: 'electro', name: 'Electro' },
      { id: 'house',   name: 'House' },
      { id: 'techno',  name: 'Techno' },
    ],
  },
  {
    id: 'decks', name: 'Decks', artIndex: 1, chartView: 'buzz_chart',
    sections: [
      { id: 'ten', name: 'Techno' },
      { id: 'hon', name: 'House' },
    ],
  },
]

const VIEWS = [
  { id: 'new_releases', label: 'Latest' },
  { id: 'chart',        label: 'Weekly Chart' },
]

const selectedView = ref('new_releases')
const sectionReleases = ref({})
const loading = ref(false)

function sectionKey(storeId, sectionId) {
  return `${storeId}__${sectionId}`
}

function triplet(store, section, viewId) {
  if (viewId === 'chart' && store.sectionlessChart) return `${store.id}-sectionless-${store.chartView}`
  const v = viewId === 'chart' ? store.chartView : viewId
  return `${store.id}-${section.id}-${v}`
}

async function loadSection(store, section, viewId) {
  const key = sectionKey(store.id, section.id)
  const t = triplet(store, section, viewId)
  try {
    const token = await auth.currentUser.getIdToken()
    const url = `${DB}/releases.json?orderBy="${t}"&startAt=0&auth=${token}`
    const data = await fetch(url).then(r => r.json())
    if (!data || typeof data !== 'object') { sectionReleases.value[key] = []; return }
    const items = Object.entries(data).map(([id, v]) => ({ id, ...v }))
    items.sort((a, b) => (a[t] ?? 999) - (b[t] ?? 999))
    sectionReleases.value[key] = items.slice(0, 10)
  } catch (e) {
    console.error(t, e)
    sectionReleases.value[key] = []
  }
}

async function loadAll() {
  loading.value = true
  const blank = {}
  for (const s of STORES) for (const sec of s.sections) blank[sectionKey(s.id, sec.id)] = []
  sectionReleases.value = blank
  await Promise.all(STORES.flatMap(s => s.sections.map(sec => loadSection(s, sec, selectedView.value))))
  loading.value = false
}

watch(user, u => { if (u) loadAll() }, { immediate: true })

function selectView(viewId) {
  selectedView.value = viewId
  loadAll()
}

function artwork(release, store) {
  const a = release.artworks
  if (!a) return null
  const urls = Array.isArray(a) ? a : Object.values(a)
  if (store.id === 'redeye') {
    return urls.find(u => u.includes('-1.')) ?? urls[0] ?? null
  }
  return urls[store.artIndex ?? 0] ?? urls[0] ?? null
}

// ── Player ────────────────────────────────────────────────────────────────────

const activeId    = ref(null)
const activeTrack = ref(0)
const isPlaying   = ref(false)
let audioEl       = null

function toArray(val) {
  if (!val) return []
  return Array.isArray(val) ? val : Object.values(val)
}

function getTracks(release)    { return toArray(release.track_urls) }
function getTrackNames(release){ return toArray(release.track_names) }

function tileClick(release) {
  if (activeId.value === release.id) {
    if (audioEl?.paused) { audioEl.play().catch(() => {}); isPlaying.value = true }
    else                 { audioEl?.pause();                isPlaying.value = false }
    return
  }
  setTrack(release, 0)
}

function setTrack(release, idx) {
  const urls = getTracks(release)
  if (!urls.length) return
  activeId.value    = release.id
  activeTrack.value = idx
  const url = urls[idx]
  if (!url) return
  if (!audioEl) {
    audioEl = new Audio()
  }
  audioEl.onended = () => {
    const next = activeTrack.value + 1
    if (next < getTracks(release).length) setTrack(release, next)
    else isPlaying.value = false
  }
  audioEl.src = url
  audioEl.play().then(() => { isPlaying.value = true }).catch(() => {})
}

function prevTrack(release, e) {
  e.stopPropagation()
  if (activeTrack.value > 0) setTrack(release, activeTrack.value - 1)
}

function nextTrack(release, e) {
  e.stopPropagation()
  const urls = getTracks(release)
  if (activeTrack.value < urls.length - 1) setTrack(release, activeTrack.value + 1)
}

function dotClick(release, dot, e) {
  e.stopPropagation()
  if (dot.index >= 0) setTrack(release, dot.index)
}

// Port of C++ compute_dots — max 5 to fit tile width
function computeDots(n, s, max = 5) {
  if (n <= max) {
    return Array.from({ length: n }, (_, i) => ({ index: i, small: false, selected: i === s }))
  }
  const half = Math.floor(max / 2)
  let start  = s - half
  let end    = start + max - 1
  if (start < 0) { start = 0;     end = max - 1 }
  if (end >= n)  { end = n - 1;   start = n - max }
  return Array.from({ length: max }, (_, i) => {
    const idx  = start + i
    const over = (start > 0 && i === 0) || (end < n - 1 && i === max - 1)
    if (over) return { index: -1, small: true, selected: false }
    return { index: idx, small: false, selected: idx === s }
  })
}
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
      </nav>
    </header>

    <div v-if="loading" class="loading">
      <img src="/spinner.png" class="spinner" alt="loading" />
    </div>

    <main v-else class="content">
      <div v-for="store in STORES" :key="store.id" class="store-block">
        <h2 class="store-name">{{ store.name }}</h2>

        <div v-for="section in store.sections" :key="section.id" class="section-row">
          <h3 class="section-name">{{ section.name }}</h3>

          <p v-if="!(sectionReleases[sectionKey(store.id, section.id)] || []).length" class="empty">no releases</p>
          <div v-else style="display:flex;flex-wrap:wrap;gap:8px">
            <div
              v-for="release in sectionReleases[sectionKey(store.id, section.id)]"
              :key="release.id"
              class="tile"
              :class="{ active: activeId === release.id, 'no-audio': !getTracks(release).length }"
              @click="getTracks(release).length && tileClick(release)"
            >
              <img
                :src="artwork(release, store) || '/white_label.jpg'"
                :alt="release.title"
                class="tile-art"
                @error="e => e.target.src = '/white_label.jpg'"
              />
              <p class="r-artist">{{ release.artist }}</p>
              <p class="r-title">{{ release.title }}</p>

              <!-- track name: only when active -->
              <p v-if="activeId === release.id" class="r-trackname">
                {{ getTrackNames(release)[activeTrack] || '' }}
              </p>

              <!-- dots: always visible if tracks exist -->
              <div v-if="getTracks(release).length" class="dots-row">
                <button
                  v-if="activeId === release.id && getTracks(release).length > 1"
                  class="nav-btn"
                  :disabled="activeTrack === 0"
                  @click="prevTrack(release, $event)"
                >&#8249;</button>

                <svg :width="computeDots(getTracks(release).length, activeId === release.id ? activeTrack : -1).length * 12" height="12">
                  <g
                    v-for="(dot, i) in computeDots(getTracks(release).length, activeId === release.id ? activeTrack : -1)"
                    :key="i"
                    style="cursor:pointer"
                    @click="dotClick(release, dot, $event)"
                  >
                    <!-- overflow small dot -->
                    <circle v-if="dot.small" :cx="i*12+6" cy="6" r="1.5" fill="#bbb" opacity="0.4" />
                    <!-- play triangle on actively playing dot -->
                    <template v-else-if="dot.selected && isPlaying">
                      <polygon :points="`${i*12+4},3 ${i*12+4},9 ${i*12+9},6`" fill="#cc4d00" />
                    </template>
                    <!-- selected but paused -->
                    <circle v-else-if="dot.selected"
                      :cx="i*12+6" cy="6" r="3.5" fill="#cc4d00" />
                    <!-- normal unselected -->
                    <circle v-else
                      :cx="i*12+6" cy="6" r="2.5"
                      :fill="activeId === release.id ? '#999' : '#ccc'"
                      :opacity="activeId === release.id ? 1 : 0.35"
                    />
                  </g>
                </svg>

                <button
                  v-if="activeId === release.id && getTracks(release).length > 1"
                  class="nav-btn"
                  :disabled="activeTrack === getTracks(release).length - 1"
                  @click="nextTrack(release, $event)"
                >&#8250;</button>
              </div>
            </div>
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

* { font-family: 'Cousine', monospace; box-sizing: border-box; }

.page {
  min-height: 100vh;
  background: #f5f5f5;
  color: #0a0a0a;
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

.viewbtn:hover { color: #333; }
.viewbtn.active { border-color: #0a0a0a; color: #0a0a0a; }

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

.store-block {
  margin-bottom: 2.5rem;
}

.store-name {
  font-size: 0.7rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: #999;
  margin: 0 0 1rem;
}

.section-row {
  margin-bottom: 1.75rem;
}

.section-name {
  font-size: 0.8rem;
  color: #333;
  margin: 0 0 0.75rem;
  font-weight: normal;
}

.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 0.75rem;
  width: 100%;
}

.tile {
  cursor: default;
}

.art {
  width: 100%;
  aspect-ratio: 1;
  background: #e0e0e0;
  margin-bottom: 0.4rem;
  overflow: hidden;
}

.art img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.tile {
  width: 120px;
  flex: 0 0 120px;
  cursor: pointer;
}

.tile-art {
  width: 120px;
  height: 120px;
  object-fit: cover;
  display: block;
}

.tile.active .tile-art {
}

.r-artist {
  font-size: 0.65rem;
  color: #0a0a0a;
  margin: 3px 0 1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: center;
}

.r-title {
  font-size: 0.6rem;
  color: #888;
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: center;
}

.r-trackname {
  font-size: 0.58rem;
  color: #cc4d00;
  margin: 3px 0 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: center;
}

.tile.no-audio { cursor: default; }

.dots-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  margin-top: 2px;
}

.dots {
  flex-shrink: 0;
}

.nav-btn {
  background: none;
  border: none;
  font-family: 'Cousine', monospace;
  font-size: 1rem;
  color: #aaa;
  cursor: pointer;
  padding: 0;
  line-height: 1;
  transition: color 0.1s;
}

.nav-btn:not(:disabled):hover { color: #333; }
.nav-btn:disabled { opacity: 0.25; cursor: default; }

.empty {
  font-size: 0.75rem;
  color: #bbb;
  padding: 0.5rem 0;
  margin: 0;
}
</style>
