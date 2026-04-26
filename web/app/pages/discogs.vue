<script setup>
const menuOpen = useState('menuOpen', () => false)

const discogsToken = ref('')

const query       = ref(localStorage.getItem('diig_dq_q')     || '')
const yearFilter  = ref(localStorage.getItem('diig_dq_year')  || '')
const genreFilter = ref(localStorage.getItem('diig_dq_genre') || '')
const styleFilter = ref(localStorage.getItem('diig_dq_style') || '')
const fmtFilter   = ref(localStorage.getItem('diig_dq_fmt') === 'Vinyl' ? '' : (localStorage.getItem('diig_dq_fmt') || ''))

const FORMATS = ['', 'Vinyl', 'LP', '12"', '7"', 'CD', 'Cassette', 'Digital', 'Box Set']

const results  = ref([])
const details  = ref({})
const loading  = ref(false)
const searched = ref(false)
const errorMsg = ref('')
const page     = ref(1)
const hasMore  = ref(false)
const sentinel = ref(null)
let   observer     = null
let   detailsAbort = null

function getHeaders() { return { Authorization: `Discogs token=${discogsToken.value}` } }

function saveFilters() {
  localStorage.setItem('diig_dq_q',     query.value)
  localStorage.setItem('diig_dq_year',  yearFilter.value)
  localStorage.setItem('diig_dq_genre', genreFilter.value)
  localStorage.setItem('diig_dq_style', styleFilter.value)
  localStorage.setItem('diig_dq_fmt',   fmtFilter.value)
}

async function search(reset = true) {
  if (!discogsToken.value) { errorMsg.value = 'Set your Discogs token in Settings'; return }
  errorMsg.value = ''

  if (detailsAbort) { detailsAbort.cancelled = true }
  detailsAbort = { cancelled: false }
  const thisAbort = detailsAbort

  if (reset) { page.value = 1; results.value = []; details.value = {} }
  loading.value  = true
  searched.value = true
  saveFilters()

  const p = new URLSearchParams({ per_page: '50', page: String(page.value) })
  if (query.value.trim())  p.set('q',      query.value.trim())
  if (yearFilter.value)    p.set('year',   yearFilter.value)
  if (genreFilter.value)   p.set('genre',  genreFilter.value)
  if (styleFilter.value)   p.set('style',  styleFilter.value)
  if (fmtFilter.value)     p.set('format', fmtFilter.value)

  try {
    const res = await fetch(`https://api.discogs.com/database/search?${p}`, { headers: getHeaders() })
    if (res.status === 429) { errorMsg.value = 'Rate limited — wait a moment and try again'; return }
    if (res.status === 401) { errorMsg.value = 'Discogs token invalid — check Settings'; return }
    if (!res.ok) { errorMsg.value = `Discogs error ${res.status}`; return }

    const data  = await res.json()
    const items = (data.results || []).filter(r => r.type === 'release' || r.type === 'master')
    results.value = reset ? items : [...results.value, ...items]
    hasMore.value  = !!data.pagination?.urls?.next
    await nextTick()
    setupObserver()
    loadDetails(items, thisAbort)
  } catch (e) {
    errorMsg.value = 'Network error — check your connection'
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function loadDetails(items, abort) {
  for (const item of items) {
    if (abort.cancelled) break
    if (!item.resource_url || item.id in details.value) continue
    details.value = { ...details.value, [item.id]: null }
    try {
      const r = await fetch(item.resource_url, { headers: getHeaders() })
      if (r.status === 429) {
        details.value = { ...details.value, [item.id]: {} }
        errorMsg.value = 'Rate limited loading track details — some tiles may lack videos'
        break
      }
      details.value = { ...details.value, [item.id]: r.ok ? await r.json() : {} }
    } catch {
      details.value = { ...details.value, [item.id]: {} }
    }
    await new Promise(r => setTimeout(r, 200))
  }
}

function setupObserver() {
  if (observer) observer.disconnect()
  if (!sentinel.value) return
  observer = new IntersectionObserver(entries => {
    if (entries[0].isIntersecting && !loading.value && hasMore.value) {
      page.value++
      search(false)
    }
  }, { rootMargin: '300px' })
  observer.observe(sentinel.value)
}

onUnmounted(() => {
  if (observer) observer.disconnect()
  if (detailsAbort) detailsAbort.cancelled = true
  ytStopAll()  // stop & destroy player when leaving the page
})

// ── Per-tile video helpers ────────────────────────────────────────────────────

function getVideos(item) { return details.value[item.id]?.videos || [] }
function videosLoading(item) { return details.value[item.id] === null }

function openRelease(item, e) {
  e.stopPropagation()
  window.open(`https://www.discogs.com${item.uri}`, '_blank', 'noopener,noreferrer')
}

function parseTitle(raw) {
  const sep = raw.indexOf(' - ')
  return sep === -1
    ? { artist: '', title: raw }
    : { artist: raw.slice(0, sep), title: raw.slice(sep + 3) }
}

function artUrl(item) { return item.cover_image || item.thumb || null }

function computeDots(count, activeIdx) {
  if (count <= 7) return Array.from({ length: count }, (_, i) => ({ small: false, selected: i === activeIdx }))
  const dots = []
  for (let i = 0; i < 7; i++) {
    const mapped = Math.round((i / 6) * (count - 1))
    const near   = activeIdx !== -1 && Math.abs(mapped - activeIdx) <= Math.round(count / 14)
    dots.push({ small: i === 0 || i === 6, selected: near && i === Math.round((activeIdx / (count - 1)) * 6) })
  }
  return dots
}

// ── YouTube composable ────────────────────────────────────────────────────────

const { ytActiveId, ytActiveTrack, ytPlaying, ytOpen, ytReleaseList,
        setTrack, toggle, close: ytClose, prevTrack, nextTrack,
        canPrev, canNext, stopAll: ytStopAll } = useYouTube()

const { stopAll: stopAudio } = useAudio()

// keep ytReleaseList in sync for cross-release navigation within discogs
watch([results, details], () => {
  ytReleaseList.value = results.value.map(item => ({
    ...item,
    videos: details.value[item.id]?.videos ?? [],
  }))
}, { deep: true })

const ytCurrentRelease = computed(() => ytReleaseList.value.find(r => String(r.id) === ytActiveId.value) ?? null)
const ytCurrentArtist  = computed(() => parseTitle(ytCurrentRelease.value?.title || '').artist || ytCurrentRelease.value?.title || '')
const ytCurrentTrack   = computed(() => ytCurrentRelease.value?.videos?.[ytActiveTrack.value]?.title || '')

function playDot(item, idx, e) {
  e.stopPropagation()
  stopAudio()  // stop stores audio player if playing
  setTrack({ ...item, videos: getVideos(item) }, idx)
}

// ── Init ──────────────────────────────────────────────────────────────────────

onMounted(() => {
  discogsToken.value = localStorage.getItem('discogsToken') || ''
  if (discogsToken.value && (query.value.trim() || yearFilter.value || genreFilter.value || styleFilter.value)) {
    search()
  }
})
</script>

<template>
  <div class="page">
    <header class="header">
      <NuxtLink to="/" class="logo">diig</NuxtLink>

      <form class="search-form" @submit.prevent="search()">
        <input
          v-model="query"
          type="search"
          placeholder="artist, label, release..."
          class="search-input"
          spellcheck="false"
          autocomplete="off"
        />
        <button type="submit" class="search-btn fa">&#xf002;</button>
      </form>

      <div class="header-right">
        <NuxtLink to="/chat"  class="chat-nav"><span class="fa">&#xf086;</span></NuxtLink>
        <NuxtLink to="/likes" class="likes-nav"><span class="fa">&#xf004;</span></NuxtLink>
        <button class="burger-btn fa" @click="menuOpen = !menuOpen">&#xf0c9;</button>
      </div>
    </header>

    <div class="filter-bar">
      <input
        v-model="yearFilter"
        type="text"
        placeholder="year"
        class="filter-input filter-year"
        @keyup.enter="search()"
      />
      <input
        v-model="genreFilter"
        type="text"
        placeholder="genre"
        class="filter-input"
        @keyup.enter="search()"
      />
      <input
        v-model="styleFilter"
        type="text"
        placeholder="style"
        class="filter-input"
        @keyup.enter="search()"
      />
      <select v-model="fmtFilter" class="filter-select" @change="search()">
        <option v-for="f in FORMATS" :key="f" :value="f">{{ f || 'all formats' }}</option>
      </select>
    </div>

    <div v-if="errorMsg" class="error-banner">{{ errorMsg }}</div>

    <div v-if="!discogsToken" class="empty-state">
      Set your Discogs token in Settings to search
    </div>

    <div v-else-if="loading && !results.length" class="loading">
      <img src="/spinner.png" class="spinner" alt="loading" />
    </div>

    <div v-else-if="searched && !results.length && !loading" class="empty-state">
      no results
    </div>

    <main v-else-if="results.length" class="content" :style="ytOpen ? 'padding-bottom: 96px' : ''">
      <div class="tile-row">
        <div
          v-for="item in results"
          :key="item.id"
          class="tile"
          :class="{ active: ytActiveId === String(item.id) }"
        >
          <p v-if="item.catno" class="r-cat">{{ item.catno }}</p>
          <p v-else class="r-cat">{{ (item.format || []).join(', ') }}</p>
          <img
            :src="artUrl(item) || '/white_label.jpg'"
            :alt="item.title"
            class="tile-art"
            @error="e => e.target.src = '/white_label.jpg'"
          />
          <p class="r-artist">{{ parseTitle(item.title).artist || item.title }}</p>
          <p class="r-title">{{ parseTitle(item.title).artist ? parseTitle(item.title).title : '' }}</p>

          <div class="icons-row">
            <div class="icons-left">
              <button
                class="icon-btn buy-btn"
                title="Open on Discogs"
                @click="openRelease(item, $event)"
              >
                <span class="fa">&#xf0ac;</span>
              </button>
            </div>
            <div class="year-tag">{{ item.year || '' }}</div>
          </div>

          <!-- Tracks (YouTube videos) -->
          <div v-if="videosLoading(item)" class="dots-row">
            <span class="no-audio-label">...</span>
          </div>
          <div v-else-if="getVideos(item).length" class="dots-row">
            <template v-for="dots in [computeDots(getVideos(item).length, ytActiveId === String(item.id) ? ytActiveTrack : -1)]" :key="0">
              <svg :width="dots.length * 12" height="12">
                <g
                  v-for="(dot, i) in dots"
                  :key="i"
                  style="cursor:pointer"
                  @click.stop="playDot(item, Math.round((i / (dots.length - 1 || 1)) * (getVideos(item).length - 1)), $event)"
                >
                  <circle v-if="dot.small" :cx="i*12+6" cy="6" r="1.5" fill="#bbb" opacity="0.4" />
                  <template v-else-if="dot.selected && ytPlaying && ytActiveId === String(item.id)">
                    <polygon :points="`${i*12+4},3 ${i*12+4},9 ${i*12+9},6`" fill="#cc4d00" />
                  </template>
                  <circle v-else-if="dot.selected" :cx="i*12+6" cy="6" r="3.5" fill="#cc4d00" />
                  <circle v-else
                    :cx="i*12+6" cy="6" r="2.5"
                    :fill="ytActiveId === String(item.id) ? '#999' : '#ccc'"
                    :opacity="ytActiveId === String(item.id) ? 1 : 0.35"
                  />
                </g>
              </svg>
            </template>
          </div>
          <div v-else-if="details[item.id] !== undefined" class="dots-row no-audio-row">
            <span class="no-audio-label">no video</span>
          </div>
          <div v-else class="dots-row" />

          <div v-if="ytActiveId === String(item.id)" class="r-trackname-wrap">
            <span class="r-trackname" :key="`${item.id}-${ytActiveTrack}`">{{ getVideos(item)[ytActiveTrack]?.title || '' }}</span>
          </div>
        </div>
      </div>

      <div v-if="loading" class="load-more-spinner">
        <img src="/spinner.png" class="spinner-sm" alt="loading" />
      </div>
      <div ref="sentinel" style="height:1px" />
    </main>

    <!-- YouTube player bar — v-show keeps #yt-iframe in DOM so the YT API can target it -->
    <div v-show="ytOpen" class="yt-bar">
      <div id="yt-iframe" class="yt-iframe" />
      <div class="yt-info">
        <p class="yt-artist">{{ ytCurrentArtist }}</p>
        <div class="r-trackname-wrap">
          <span class="r-trackname" :key="`${ytActiveId}-${ytActiveTrack}`">{{ ytCurrentTrack }}</span>
        </div>
      </div>
      <div class="yt-controls">
        <button class="yt-btn nav-btn" :disabled="!canPrev" @click="prevTrack()">&#8249;</button>
        <button class="yt-btn play-btn" @click="toggle()">
          <span v-if="ytPlaying">&#9646;&#9646;</span><span v-else>&#9654;</span>
        </button>
        <button class="yt-btn nav-btn" :disabled="!canNext" @click="nextTrack()">&#8250;</button>
      </div>
      <button class="yt-close" @click="ytClose()">&#10005;</button>
    </div>
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
}

.header {
  display: flex;
  align-items: center;
  gap: 1rem;
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
  color: #0a0a0a;
  text-decoration: none;
  white-space: nowrap;
}

.search-form {
  flex: 1;
  display: flex;
  gap: 0.4rem;
  min-width: 0;
}

.search-input {
  flex: 1;
  padding: 0.35rem 0.6rem;
  font-size: 0.75rem;
  font-family: 'Cousine', monospace;
  border: 1px solid #ddd;
  border-radius: 3px;
  outline: none;
  background: #f9f9f9;
  color: #333;
  min-width: 0;
}
.search-input:focus { border-color: #aaa; background: #fff; }

.search-btn {
  padding: 0.35rem 0.7rem;
  background: #0a0a0a;
  color: #fff;
  border: none;
  border-radius: 3px;
  cursor: pointer;
  font-size: 0.75rem;
  white-space: nowrap;
}
.search-btn:hover { background: #333; }

.header-right {
  display: flex;
  align-items: center;
  gap: 0.9rem;
  flex-shrink: 0;
}

.chat-nav, .likes-nav {
  font-size: 1rem;
  color: #ccc;
  text-decoration: none;
  transition: color 0.15s;
}
.chat-nav:hover  { color: #555; }
.likes-nav:hover { color: #e03070; }

.filter-bar {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.6rem 1.5rem;
  background: #fff;
  border-bottom: 1px solid #ececec;
  flex-wrap: wrap;
}

.filter-input {
  padding: 0.28rem 0.5rem;
  font-size: 0.65rem;
  font-family: 'Cousine', monospace;
  border: 1px solid #e0e0e0;
  border-radius: 3px;
  outline: none;
  width: 100px;
  color: #444;
  background: #fafafa;
}
.filter-input:focus { border-color: #aaa; background: #fff; }
.filter-year { width: 60px; }

.filter-select {
  padding: 0.28rem 0.5rem;
  font-size: 0.65rem;
  font-family: 'Cousine', monospace;
  border: 1px solid #e0e0e0;
  border-radius: 3px;
  outline: none;
  color: #444;
  background: #fafafa;
  cursor: pointer;
}
.filter-select:focus { border-color: #aaa; }

.empty-state {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 40vh;
  font-size: 0.7rem;
  color: #bbb;
}

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

.spinner-sm {
  width: 40px;
  height: 40px;
  animation: spin 1.2s linear infinite;
}

.load-more-spinner {
  display: flex;
  justify-content: center;
  padding: 1.5rem;
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

.tile {
  width: 150px;
  flex: 0 0 150px;
}

.tile-art {
  width: 150px;
  height: 150px;
  object-fit: cover;
  display: block;
}

.r-cat {
  font-size: 0.55rem;
  color: #bbb;
  margin: 0 0 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.r-artist {
  font-size: 0.65rem;
  color: #0a0a0a;
  margin: 3px 0 1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.r-title {
  font-size: 0.6rem;
  color: #888;
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-height: 1em;
}

.icons-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 4px;
  height: 16px;
}

.icons-left {
  display: flex;
  align-items: center;
  gap: 5px;
}

.icon-btn {
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  display: flex;
  align-items: center;
  color: #bbb;
  font-size: 0.75rem;
  line-height: 1;
  transition: color 0.15s;
}
.buy-btn:hover { color: #333; }

.year-tag {
  font-size: 0.55rem;
  color: #bbb;
  letter-spacing: 0.02em;
}

.dots-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  margin-top: 2px;
  height: 16px;
}

.no-audio-label {
  font-size: 0.5rem;
  color: #ddd;
  letter-spacing: 0.05em;
}

@media (max-width: 600px) {
  .tile     { width: 100%; flex: 0 0 100%; }
  .tile-art { width: 100%; height: auto; aspect-ratio: 1; }
  .header   { padding: 0.75rem 1rem; gap: 0.6rem; }
}

.error-banner {
  padding: 0.5rem 1.5rem;
  font-size: 0.65rem;
  color: #c44;
  background: #fff8f8;
  border-bottom: 1px solid #fde;
}

/* ── Track name marquee (tile) ────────────────────────────────────────────── */

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
  80%, 100% { transform: translateX(min(0px, calc(150px - 100%))); }
}

@media (max-width: 600px) {
  @keyframes trackscroll {
    0%,  20% { transform: translateX(0); }
    80%, 100% { transform: translateX(min(0px, calc(100vw - 3rem - 100%))); }
  }
}

/* ── YouTube player bar ───────────────────────────────────────────────────── */

.yt-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 200;
  height: 80px;
  background: #0a0a0a;
  border-top: 1px solid #222;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.5rem 1rem;
}

.yt-iframe {
  flex-shrink: 0;
  width: 120px;
  height: 68px;
  background: #000;
  overflow: hidden;
}

.yt-info {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.yt-artist {
  font-size: 0.55rem;
  color: #666;
  margin: 0 0 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.yt-controls {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  flex-shrink: 0;
}

.yt-btn {
  background: none;
  border: none;
  color: #ccc;
  cursor: pointer;
  font-family: 'Cousine', monospace;
  line-height: 1;
  padding: 0.3rem 0.4rem;
  transition: color 0.1s;
}
.yt-btn.nav-btn  { font-size: 1.4rem; }
.yt-btn.play-btn { font-size: 0.75rem; }
.yt-btn:disabled { opacity: 0.25; cursor: default; }
.yt-btn:not(:disabled):hover { color: #cc4d00; }

.yt-close {
  background: none;
  border: none;
  color: #444;
  cursor: pointer;
  font-family: 'Cousine', monospace;
  font-size: 0.65rem;
  padding: 0.3rem 0.4rem;
  flex-shrink: 0;
  transition: color 0.1s;
}
.yt-close:hover { color: #aaa; }
</style>
