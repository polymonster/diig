<script setup>
import { DISCOGS_GENRES, DISCOGS_STYLES } from '~/utils/discogs_taxonomy'

const menuOpen = useState('menuOpen', () => false)
const { isLive } = useLiveStatus()

const discogsToken = ref(localStorage.getItem('discogsToken') || '')

function loadArray(key) {
  try { const v = JSON.parse(localStorage.getItem(key) || '[]'); return Array.isArray(v) ? v : [] }
  catch { return [] }
}

const query      = ref(localStorage.getItem('diig_dq_q')    || '')
const yearFilter = ref(localStorage.getItem('diig_dq_year') || '')
const genres     = ref(loadArray('diig_dq_genres'))
const styles     = ref(loadArray('diig_dq_styles'))
const genreInput = ref('')
const styleInput = ref('')
const fmtFilter  = ref(localStorage.getItem('diig_dq_fmt') === 'Vinyl' ? '' : (localStorage.getItem('diig_dq_fmt') || ''))

const FORMATS  = ['', 'Vinyl', 'LP', '12"', '7"', 'CD', 'Cassette', 'Digital', 'Box Set']
const SORT_MODES = [
  { value: '',          label: 'relevance' },
  { value: 'year-desc', label: 'year ↓' },
  { value: 'year-asc',  label: 'year ↑' },
]

const results  = ref([])
const details  = ref({})
const loading  = ref(false)
const searched = ref(false)
const errorMsg = ref('')
const page     = ref(1)
const hasMore  = ref(false)
const sentinel = ref(null)
let   observer        = null
let   cooldownTimer   = null
let   detailsQueue    = []
let   detailsRunning  = false
let   detailsStop     = false

const cooldown     = ref(false)
const busy         = computed(() => loading.value || cooldown.value)
const sortMode     = ref('')
const artistFilter = ref('')
const labelFilter  = ref('')

const displayResults = computed(() => {
  let r = results.value
  const yr = parseYearRange(yearFilter.value)
  if (yr) r = r.filter(i => { const y = parseInt(i.year); return y >= yr[0] && y <= yr[1] })
  if (artistFilter.value) r = r.filter(i => parseTitle(i.title).artist === artistFilter.value)
  if (labelFilter.value)  r = r.filter(i => (details.value[i.id]?.labels ?? []).some(l => l.name === labelFilter.value))
  return r
})

// a single exact year is sent to the api; a range like 1990-2000 has no api
// equivalent so it filters loaded results client-side
function parseYearRange(raw) {
  const m = raw.trim().match(/^(\d{4})\s*-\s*(\d{4})$/)
  if (!m) return null
  let a = +m[1], b = +m[2]
  if (a > b) [a, b] = [b, a]
  return [a, b]
}

// genre/style typeahead over the curated taxonomy; free-typed values allowed too
function suggestions(pool, input, selected) {
  const q = input.trim().toLowerCase()
  const sel = new Set(selected.map(s => s.toLowerCase()))
  return pool
    .filter(o => !sel.has(o.toLowerCase()) && (!q || o.toLowerCase().includes(q)))
    .slice(0, 8)
}
const genreSuggestions = computed(() => genreInput.value ? suggestions(DISCOGS_GENRES, genreInput.value, genres.value) : [])
const styleSuggestions = computed(() => styleInput.value ? suggestions(DISCOGS_STYLES, styleInput.value, styles.value) : [])

// keyed by 'genre'/'style' rather than passing the refs — in the template
// top-level refs are auto-unwrapped, so a ref passed as an arg arrives as its
// plain value and could not be mutated
function chipRefs(kind) {
  return kind === 'genre'
    ? { list: genres, input: genreInput }
    : { list: styles, input: styleInput }
}
function addChip(kind, value) {
  const { list, input } = chipRefs(kind)
  const v = (value ?? input.value).trim()
  if (!v) return
  if (!list.value.some(x => x.toLowerCase() === v.toLowerCase())) list.value = [...list.value, v]
  input.value = ''
  if (searched.value && !busy.value) search()
}
function removeChip(kind, value) {
  const { list } = chipRefs(kind)
  list.value = list.value.filter(x => x !== value)
  if (searched.value && !busy.value) search()
}

function startCooldown(secs = 8) {
  cooldown.value = true
  clearTimeout(cooldownTimer)
  cooldownTimer = setTimeout(() => { cooldown.value = false }, secs * 1000)
}

watch(cooldown, val => {
  if (!val && detailsQueue.length) setTimeout(drainDetails, 0)
})

watch(sortMode, () => { if (searched.value && !busy.value) search() })

function getHeaders() { return { Authorization: `Discogs token=${discogsToken.value}` } }

function saveFilters() {
  localStorage.setItem('diig_dq_q',      query.value)
  localStorage.setItem('diig_dq_year',   yearFilter.value)
  localStorage.setItem('diig_dq_genres', JSON.stringify(genres.value))
  localStorage.setItem('diig_dq_styles', JSON.stringify(styles.value))
  localStorage.setItem('diig_dq_fmt',    fmtFilter.value)
}

async function search(reset = true) {
  if (!discogsToken.value) { errorMsg.value = 'Set your Discogs token in Settings'; return }
  if (busy.value) return
  errorMsg.value = ''

  if (reset) {
    detailsStop = true
    detailsQueue = []
    page.value = 1; results.value = []; details.value = {}
    artistFilter.value = ''; labelFilter.value = ''
  }
  loading.value  = true
  searched.value = true
  saveFilters()

  const p = new URLSearchParams({ per_page: '50', page: String(page.value) })
  if (query.value.trim()) p.set('q', query.value.trim())

  // exact year -> api param; a range is applied client-side in displayResults
  const yr = yearFilter.value.trim()
  if (/^\d{4}$/.test(yr)) p.set('year', yr)

  // repeated genre/style params narrow results (discogs ANDs them)
  for (const g of genres.value) p.append('genre', g)
  for (const s of styles.value) p.append('style', s)
  if (fmtFilter.value) p.set('format', fmtFilter.value)
  if (sortMode.value)  { p.set('sort', 'year'); p.set('sort_order', sortMode.value === 'year-asc' ? 'asc' : 'desc') }

  try {
    const res = await fetch(`https://api.discogs.com/database/search?${p}`, { headers: getHeaders() })
    if (res.status === 429) { errorMsg.value = 'Rate limited — wait a moment and try again'; startCooldown(); return }
    if (res.status === 401) { errorMsg.value = 'Discogs token invalid — check Settings'; return }
    if (!res.ok) { errorMsg.value = `Discogs error ${res.status}`; return }

    const data = await res.json()
    const seen = new Set()
    const items = (data.results || []).filter(r => {
      if (r.type !== 'release' && r.type !== 'master') return false
      const key = r.master_id ? String(r.master_id) : `r-${r.id}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    results.value = reset ? items : [...results.value, ...items]
    hasMore.value  = !!data.pagination?.urls?.next
    await nextTick()
    setupObserver()
    detailsQueue.push(...items.filter(i => i.resource_url && !(i.id in details.value)))
    setTimeout(drainDetails, 0)
  } catch (e) {
    errorMsg.value = 'Discogs request failed — try again'
    console.error(e)
  } finally {
    loading.value = false
  }
}

function resetDetailItem(id) {
  const { [id]: _, ...rest } = details.value
  details.value = rest
}

async function drainDetails() {
  if (detailsRunning) return
  detailsRunning = true
  detailsStop = false
  while (detailsQueue.length && !detailsStop) {
    const item = detailsQueue.shift()
    if (!item.resource_url || item.id in details.value) continue
    details.value = { ...details.value, [item.id]: null }
    try {
      const r = await fetch(item.resource_url, { headers: getHeaders() })
      if (r.status === 429) {
        resetDetailItem(item.id)
        detailsQueue.unshift(item)
        errorMsg.value = 'Discogs rate limit reached — video loading will resume shortly'
        startCooldown()
        break
      }
      details.value = { ...details.value, [item.id]: r.ok ? await r.json() : {} }
    } catch {
      resetDetailItem(item.id)
      detailsQueue.unshift(item)
      errorMsg.value = 'Discogs request interrupted — retrying shortly'
      startCooldown(5)
      break
    }
    await new Promise(r => setTimeout(r, 1200))
  }
  detailsRunning = false
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
  detailsStop = true
  detailsQueue = []
  ytStopAll()
})

// ── Per-tile video helpers ────────────────────────────────────────────────────

function getVideos(item) { return details.value[item.id]?.videos || [] }
function detailsFetched(item) { return item.id in details.value && details.value[item.id] !== null }

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

const { activeId: ytActiveId, activeTrack: ytActiveTrack, isPlaying: ytPlaying,
        releaseList: ytReleaseList, activeRelease: ytActiveRelease,
        playVideo, tileClickVideo, prevTrack, nextTrack,
        stopAll: ytStopAll } = usePlayer()

function tileTap(item, e) {
  e.stopPropagation()
  const videos = getVideos(item)
  if (!videos.length) return
  tileClickVideo({ ...item, videos })
}

// keep ytReleaseList in sync — use displayResults so navigation follows visible items
watch([results, details, artistFilter, labelFilter], () => {
  ytReleaseList.value = displayResults.value.map(item => ({
    ...item,
    videos: details.value[item.id]?.videos ?? [],
  }))
}, { deep: true })

function playDot(item, idx, e) {
  e.stopPropagation()
  playVideo({ ...item, videos: getVideos(item) }, idx)
}

// ── Init ──────────────────────────────────────────────────────────────────────

onMounted(() => {
  if (discogsToken.value && (query.value.trim() || yearFilter.value || genres.value.length || styles.value.length)) {
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
        <button type="submit" class="search-btn" :class="{ 'search-btn-busy': busy }" :disabled="busy">
          <span v-if="busy" class="search-spinner" />
          <span v-else class="fa">&#xf002;</span>
        </button>
      </form>

      <div class="header-right">
        <NuxtLink v-if="isLive" to="/live" class="live-nav">
          <span class="live-nav-dot" />live
        </NuxtLink>
        <NuxtLink to="/likes" class="likes-nav"><span class="fa">&#xf004;</span></NuxtLink>
        <button class="burger-btn fa" @click="menuOpen = !menuOpen">&#xf0c9;</button>
      </div>
    </header>

    <div class="filter-bar">
      <input
        v-model="yearFilter"
        type="text"
        placeholder="year / 1990-2000"
        class="filter-input filter-year"
        @keyup.enter="!busy && search()"
      />
      <div class="ta">
        <input
          v-model="genreInput"
          type="text"
          placeholder="+ genre"
          class="filter-input"
          spellcheck="false"
          autocomplete="off"
          @keyup.enter.prevent="addChip('genre', genreSuggestions[0])"
          @keydown.tab="genreSuggestions[0] && addChip('genre', genreSuggestions[0])"
        />
        <ul v-if="genreSuggestions.length" class="ta-menu">
          <li v-for="s in genreSuggestions" :key="s" @mousedown.prevent="addChip('genre', s)">{{ s }}</li>
        </ul>
      </div>
      <div class="ta">
        <input
          v-model="styleInput"
          type="text"
          placeholder="+ style"
          class="filter-input"
          spellcheck="false"
          autocomplete="off"
          @keyup.enter.prevent="addChip('style', styleSuggestions[0])"
          @keydown.tab="styleSuggestions[0] && addChip('style', styleSuggestions[0])"
        />
        <ul v-if="styleSuggestions.length" class="ta-menu">
          <li v-for="s in styleSuggestions" :key="s" @mousedown.prevent="addChip('style', s)">{{ s }}</li>
        </ul>
      </div>
      <select v-model="fmtFilter" class="filter-select" @change="!busy && search()">
        <option v-for="f in FORMATS" :key="f" :value="f">{{ f || 'all formats' }}</option>
      </select>
      <select v-model="sortMode" class="filter-select sort-select">
        <option v-for="s in SORT_MODES" :key="s.value" :value="s.value">{{ s.label }}</option>
      </select>
    </div>

    <div v-if="genres.length || styles.length" class="active-filters">
      <span v-for="g in genres" :key="'g-' + g" class="filter-chip">
        {{ g }}
        <button class="chip-clear" @click="removeChip('genre', g)">&#10005;</button>
      </span>
      <span v-for="s in styles" :key="'s-' + s" class="filter-chip filter-chip-style">
        {{ s }}
        <button class="chip-clear" @click="removeChip('style', s)">&#10005;</button>
      </span>
    </div>

    <div v-if="artistFilter || labelFilter" class="active-filters">
      <span v-if="artistFilter" class="filter-chip">
        artist: {{ artistFilter }}
        <button class="chip-clear" @click="artistFilter = ''">&#10005;</button>
      </span>
      <span v-if="labelFilter" class="filter-chip">
        label: {{ labelFilter }}
        <button class="chip-clear" @click="labelFilter = ''">&#10005;</button>
      </span>
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

    <div v-else-if="results.length && !displayResults.length" class="empty-state">
      no results match filters
    </div>

    <main v-else-if="displayResults.length" class="content" :style="ytActiveRelease ? 'padding-bottom: 96px' : ''">
      <div class="tile-row">
        <div
          v-for="item in displayResults"
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
            :class="{ 'has-video': getVideos(item).length }"
            @click="tileTap(item, $event)"
            @error="e => e.target.src = '/white_label.jpg'"
          />
          <p
            class="r-artist"
            :class="{ 'r-filterable': parseTitle(item.title).artist }"
            @click.stop="parseTitle(item.title).artist && (artistFilter = parseTitle(item.title).artist)"
          >{{ parseTitle(item.title).artist || item.title }}</p>
          <p class="r-title">{{ parseTitle(item.title).artist ? parseTitle(item.title).title : '' }}</p>
          <p
            v-if="details[item.id]?.labels?.[0]?.name"
            class="r-label r-filterable"
            @click.stop="labelFilter = details[item.id].labels[0].name"
          >{{ details[item.id].labels[0].name }}</p>

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
          <div v-if="getVideos(item).length" class="dots-row">
            <button
              v-if="ytActiveId === String(item.id) && getVideos(item).length > 1"
              class="nav-btn"
              :disabled="ytActiveTrack === 0"
              @click.stop="prevTrack($event)"
            >&#8249;</button>

            <template v-for="(dots, i) in [computeDots(getVideos(item).length, ytActiveId === String(item.id) ? ytActiveTrack : -1)]" :key="i">
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

            <button
              v-if="ytActiveId === String(item.id) && getVideos(item).length > 1"
              class="nav-btn"
              :disabled="ytActiveTrack === getVideos(item).length - 1"
              @click.stop="nextTrack($event)"
            >&#8250;</button>
          </div>
          <div v-else-if="detailsFetched(item)" class="dots-row no-audio-row">
            <span class="no-audio-label">no video</span>
          </div>
          <div v-else class="dots-row">
            <span class="no-audio-label dots-pending">...</span>
          </div>

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

    <!-- YT iframe always in DOM, off-screen so YouTube can play freely -->
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
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 2rem;
}
.search-btn:hover:not(:disabled) { background: #333; }
.search-btn:disabled { opacity: 0.5; cursor: default; }

.search-spinner {
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 0.9rem;
  flex-shrink: 0;
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
.filter-year { width: 110px; }

.ta { position: relative; display: inline-block; }

.ta-menu {
  position: absolute;
  top: 100%;
  left: 0;
  z-index: 20;
  margin: 2px 0 0;
  padding: 2px;
  list-style: none;
  background: #fff;
  border: 1px solid #ddd;
  border-radius: 3px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  min-width: 150px;
  max-height: 220px;
  overflow-y: auto;
}

.ta-menu li {
  padding: 0.3rem 0.5rem;
  font-size: 0.65rem;
  font-family: 'Cousine', monospace;
  color: #444;
  cursor: pointer;
  white-space: nowrap;
}
.ta-menu li:hover { background: #f0f0f0; color: #0a0a0a; }

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
.sort-select { margin-left: auto; }

.active-filters {
  display: flex;
  gap: 0.4rem;
  padding: 0.4rem 1.5rem;
  background: #fff;
  border-bottom: 1px solid #ececec;
  flex-wrap: wrap;
}

.filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.18rem 0.5rem;
  font-size: 0.6rem;
  font-family: 'Cousine', monospace;
  background: #0a0a0a;
  color: #fff;
  border-radius: 2px;
}

.chip-clear {
  background: none;
  border: none;
  color: #aaa;
  cursor: pointer;
  padding: 0;
  font-size: 0.55rem;
  line-height: 1;
  font-family: 'Cousine', monospace;
}
.chip-clear:hover { color: #fff; }

.filter-chip-style { background: #444; }

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
.tile-art.has-video { cursor: pointer; }

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

.r-label {
  font-size: 0.55rem;
  color: #bbb;
  margin: 1px 0 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.r-filterable {
  cursor: pointer;
}
.r-filterable:hover { text-decoration: underline; text-decoration-style: dotted; }

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

.dots-pending {
  display: inline-block;
  overflow: hidden;
  white-space: nowrap;
  animation: dotgrow 1.5s steps(3, end) infinite;
}

@keyframes dotgrow {
  from { max-width: 1ch; }
  to   { max-width: 4ch; }
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

</style>
