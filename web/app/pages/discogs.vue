<script setup lang="ts">
import type { DiscogsResult, DiscogsDetails } from '~/composables/useDiscogs'

// Search the discogs database with the user's own token. Results come from
// /database/search; each result's videos (and label) need the full record, so
// those are fetched one by one in the background, gently, to stay under
// discogs' rate limit of 60 requests a minute

const discogs = useDiscogs()
const { releaseList, stopAll } = usePlayer()

const FORMATS = ['', 'Vinyl', 'LP', '12"', '7"', 'CD', 'Cassette', 'Digital', 'Box Set']
const SORT_MODES = [
  { value: '',          label: 'relevance' },
  { value: 'year-desc', label: 'year ↓' },
  { value: 'year-asc',  label: 'year ↑' },
]

// ── Filters (remembered in the browser) ──────────────────────────────────────

const query      = ref(storageGet('diig_dq_q'))
const yearFilter = ref(storageGet('diig_dq_year'))
const genres     = ref<string[]>(storageGetJson('diig_dq_genres', []))
const styles     = ref<string[]>(storageGetJson('diig_dq_styles', []))
// 'Vinyl' was once the default, a stored one reads as no format filter
const fmtFilter  = ref(storageGet('diig_dq_fmt') === 'Vinyl' ? '' : storageGet('diig_dq_fmt'))
const sortMode   = ref('')

function saveFilters() {
  storageSet('diig_dq_q',      query.value)
  storageSet('diig_dq_year',   yearFilter.value)
  storageSet('diig_dq_genres', genres.value)
  storageSet('diig_dq_styles', styles.value)
  storageSet('diig_dq_fmt',    fmtFilter.value)
}

// filters on the loaded results, set by clicking an artist or label on a tile
const artistFilter = ref('')
const labelFilter  = ref('')

// a single exact year is sent to the api; a range like 1990-2000 has no api
// equivalent so it filters the loaded results
function parseYearRange(raw: string): [number, number] | null {
  const m = raw.trim().match(/^(\d{4})\s*-\s*(\d{4})$/)
  if (!m) return null
  const a = +m[1]!, b = +m[2]!
  return a <= b ? [a, b] : [b, a]
}

// ── Genre / style chips ──────────────────────────────────────────────────────

// typeahead over the curated taxonomy; free-typed values are allowed too
const genreInput = ref('')
const styleInput = ref('')

function suggest(pool: string[], input: string, selected: string[]): string[] {
  const q = input.trim().toLowerCase()
  if (!q) return []
  const sel = new Set(selected.map(s => s.toLowerCase()))
  return pool.filter(o => !sel.has(o.toLowerCase()) && o.toLowerCase().includes(q)).slice(0, 8)
}

const genreSuggestions = computed(() => suggest(DISCOGS_GENRES, genreInput.value, genres.value))
const styleSuggestions = computed(() => suggest(DISCOGS_STYLES, styleInput.value, styles.value))

type ChipKind = 'genre' | 'style'

// by kind rather than passing the refs: in the template top-level refs are
// auto-unwrapped, so a ref passed as an argument arrives as its plain value
function chipRefs(kind: ChipKind) {
  return kind === 'genre'
    ? { list: genres, input: genreInput }
    : { list: styles, input: styleInput }
}

function addChip(kind: ChipKind, value?: string) {
  const { list, input } = chipRefs(kind)
  const v = (value ?? input.value).trim()
  if (!v) return
  if (!list.value.some(x => x.toLowerCase() === v.toLowerCase())) list.value = [...list.value, v]
  input.value = ''
  refresh()
}

function removeChip(kind: ChipKind, value: string) {
  const { list } = chipRefs(kind)
  list.value = list.value.filter(x => x !== value)
  refresh()
}

// ── Search ───────────────────────────────────────────────────────────────────

const results  = ref<DiscogsResult[]>([])
const loading  = ref(false)
const searched = ref(false)
const errorMsg = ref('')
const page     = ref(1)
const hasMore  = ref(false)

// after a 429 nothing is sent until this clears
const cooldown = ref(false)
let cooldownTimer: ReturnType<typeof setTimeout> | undefined

const busy = computed(() => loading.value || cooldown.value)

function startCooldown(secs = 8) {
  cooldown.value = true
  clearTimeout(cooldownTimer)
  cooldownTimer = setTimeout(() => { cooldown.value = false }, secs * 1000)
}

// rerun the current search after a filter change
function refresh() {
  if (searched.value && !busy.value) search()
}

function searchParams(): URLSearchParams {
  const p = new URLSearchParams({ per_page: '50', page: String(page.value) })
  if (query.value.trim()) p.set('q', query.value.trim())
  // an exact year goes to the api, a range is applied in displayResults
  const yr = yearFilter.value.trim()
  if (/^\d{4}$/.test(yr)) p.set('year', yr)
  // repeated genre / style params narrow the results (discogs ANDs them)
  for (const g of genres.value) p.append('genre', g)
  for (const s of styles.value) p.append('style', s)
  if (fmtFilter.value) p.set('format', fmtFilter.value)
  if (sortMode.value) {
    p.set('sort', 'year')
    p.set('sort_order', sortMode.value === 'year-asc' ? 'asc' : 'desc')
  }
  return p
}

// reset: a new search from page one, otherwise the next page of this one
async function search(reset = true) {
  if (!discogs.token.value) { errorMsg.value = 'Set your Discogs token in Settings'; return }
  if (busy.value) return
  errorMsg.value = ''

  if (reset) {
    stopDetails()
    page.value         = 1
    results.value      = []
    details.value      = {}
    artistFilter.value = ''
    labelFilter.value  = ''
  }
  loading.value  = true
  searched.value = true
  saveFilters()

  try {
    const res = await fetch(`${DISCOGS_API}/database/search?${searchParams()}`, { headers: discogs.headers() })
    if (res.status === 429) { errorMsg.value = 'Rate limited — wait a moment and try again'; startCooldown(); return }
    if (res.status === 401) { errorMsg.value = 'Discogs token invalid — check Settings'; return }
    if (!res.ok)            { errorMsg.value = `Discogs error ${res.status}`; return }

    const data = await res.json()
    // releases and masters only, one per master
    const seen  = new Set<string>()
    const items = (data.results as DiscogsResult[] || []).filter(r => {
      if (r.type !== 'release' && r.type !== 'master') return false
      const key = r.master_id ? String(r.master_id) : `r-${r.id}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    results.value = reset ? items : [...results.value, ...items]
    hasMore.value = !!data.pagination?.urls?.next
    queueDetails(items)
  } catch (e) {
    errorMsg.value = 'Discogs request failed — try again'
    console.error(e)
  } finally {
    loading.value = false
  }
}

watch(sortMode, refresh)

const displayResults = computed(() => {
  let r = results.value
  const yr = parseYearRange(yearFilter.value)
  if (yr) r = r.filter(i => { const y = parseInt(i.year ?? ''); return y >= yr[0] && y <= yr[1] })
  if (artistFilter.value) r = r.filter(i => parseTitle(i.title).artist === artistFilter.value)
  if (labelFilter.value)  r = r.filter(i => (details.value[i.id]?.labels ?? []).some(l => l.name === labelFilter.value))
  return r
})

// ── Details (videos, labels) ─────────────────────────────────────────────────

// result id -> full record. no key: not fetched yet, null: in flight
const details = ref<Record<number, DiscogsDetails | null>>({})

let detailsQueue: DiscogsResult[] = []
let detailsRunning = false
let detailsStop    = false

function queueDetails(items: DiscogsResult[]) {
  detailsQueue.push(...items.filter(i => i.resource_url && !(i.id in details.value)))
  drainDetails()
}

function stopDetails() {
  detailsStop  = true
  detailsQueue = []
}

// give an item back to the queue to retry after a cooldown
function requeue(item: DiscogsResult, msg: string, secs?: number) {
  const { [item.id]: _, ...rest } = details.value
  details.value = rest
  detailsQueue.unshift(item)
  errorMsg.value = msg
  startCooldown(secs)
}

async function drainDetails() {
  if (detailsRunning) return
  detailsRunning = true
  detailsStop    = false
  while (detailsQueue.length && !detailsStop) {
    const item = detailsQueue.shift()!
    if (item.id in details.value) continue
    details.value = { ...details.value, [item.id]: null }
    try {
      const r = await fetch(item.resource_url!, { headers: discogs.headers() })
      if (r.status === 429) {
        requeue(item, 'Discogs rate limit reached — video loading will resume shortly')
        break
      }
      details.value = { ...details.value, [item.id]: r.ok ? await r.json() : {} }
    } catch {
      requeue(item, 'Discogs request interrupted — retrying shortly', 5)
      break
    }
    await new Promise(r => setTimeout(r, 1200))
  }
  detailsRunning = false
}

// pick the queue back up when a rate limit cooldown ends
watch(cooldown, val => { if (!val && detailsQueue.length) drainDetails() })

// the player steps through the visible results, with their videos
watch([displayResults, details], () => {
  releaseList.value = displayResults.value.map(item => ({
    ...item,
    id:     String(item.id),
    videos: details.value[item.id]?.videos ?? [],
  }))
})

// ── Infinite scroll ──────────────────────────────────────────────────────────

const sentinel = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null

onMounted(() => {
  observer = new IntersectionObserver(entries => {
    if (entries[0]?.isIntersecting && !loading.value && hasMore.value) {
      page.value++
      search(false)
    }
  }, { rootMargin: '300px' })
})
watch(sentinel, el => {
  observer?.disconnect()
  if (el) observer?.observe(el)
})

// ── Lifecycle ────────────────────────────────────────────────────────────────

onMounted(() => {
  // rerun the remembered search
  if (discogs.token.value && (query.value.trim() || yearFilter.value || genres.value.length || styles.value.length)) {
    search()
  }
})

onUnmounted(() => {
  observer?.disconnect()
  stopDetails()
  stopAll()
})
</script>

<template>
  <div class="page">
    <AppHeader>
      <form class="search-form" @submit.prevent="search()">
        <input
          v-model="query"
          type="search"
          placeholder="artist, label, release..."
          class="search-input"
          spellcheck="false"
          autocomplete="off"
        >
        <button type="submit" class="btn-sm search-btn" :disabled="busy">
          <span v-if="busy" class="search-spinner" />
          <span v-else class="fa">{{ ICON.search }}</span>
        </button>
      </form>
    </AppHeader>

    <div class="filter-bar">
      <input
        v-model="yearFilter"
        type="text"
        placeholder="year / 1990-2000"
        class="filter-input year"
        @keyup.enter="refresh"
      >
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
        >
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
        >
        <ul v-if="styleSuggestions.length" class="ta-menu">
          <li v-for="s in styleSuggestions" :key="s" @mousedown.prevent="addChip('style', s)">{{ s }}</li>
        </ul>
      </div>
      <select v-model="fmtFilter" class="filter-input" @change="refresh">
        <option v-for="f in FORMATS" :key="f" :value="f">{{ f || 'all formats' }}</option>
      </select>
      <select v-model="sortMode" class="filter-input sort">
        <option v-for="s in SORT_MODES" :key="s.value" :value="s.value">{{ s.label }}</option>
      </select>
    </div>

    <div v-if="genres.length || styles.length || artistFilter || labelFilter" class="filter-bar chips">
      <span v-for="g in genres" :key="'g-' + g" class="chip">
        {{ g }}<button class="chip-clear" @click="removeChip('genre', g)">&#10005;</button>
      </span>
      <span v-for="s in styles" :key="'s-' + s" class="chip style">
        {{ s }}<button class="chip-clear" @click="removeChip('style', s)">&#10005;</button>
      </span>
      <span v-if="artistFilter" class="chip">
        artist: {{ artistFilter }}<button class="chip-clear" @click="artistFilter = ''">&#10005;</button>
      </span>
      <span v-if="labelFilter" class="chip">
        label: {{ labelFilter }}<button class="chip-clear" @click="labelFilter = ''">&#10005;</button>
      </span>
    </div>

    <div v-if="errorMsg" class="error-banner">{{ errorMsg }}</div>

    <p v-if="!discogs.token.value" class="empty">Set your Discogs token in Settings to search</p>
    <LoadingSpinner v-else-if="loading && !results.length" full />
    <p v-else-if="searched && !results.length" class="empty">no results</p>
    <p v-else-if="results.length && !displayResults.length" class="empty">no results match filters</p>

    <main v-else-if="displayResults.length" class="content">
      <div class="shelf">
        <DiscogsTile
          v-for="item in displayResults"
          :key="item.id"
          :item="item"
          :details="details[item.id]"
          @artist="name => artistFilter = name"
          @label="name => labelFilter = name"
        />
      </div>
      <LoadingSpinner v-if="loading" />
      <div ref="sentinel" class="sentinel" />
    </main>
  </div>
</template>

<style scoped>
/* ── Search box (in the header) ── */

.search-form {
  flex: 1;
  display: flex;
  gap: 0.4rem;
  min-width: 0;
}

.search-input {
  flex: 1;
  min-width: 0;
  padding: 0.35rem 0.6rem;
  font-size: 0.75rem;
  border: 1px solid #ddd;
  border-radius: 3px;
  outline: none;
  background: #f9f9f9;
  color: #333;
}
.search-input:focus { border-color: #aaa; background: #fff; }

.search-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 2rem;
  font-size: 0.75rem;
}

.search-spinner {
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ── Filters ── */

.year { width: 110px; }
.sort { margin-left: auto; cursor: pointer; }
select.filter-input { cursor: pointer; }
.ta .filter-input { width: 100px; }

/* typeahead */
.ta { position: relative; }

.ta-menu {
  position: absolute;
  top: 100%;
  left: 0;
  z-index: 20;
  margin: 2px 0 0;
  padding: 2px;
  background: #fff;
  border: 1px solid #ddd;
  border-radius: 3px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  min-width: 150px;
  max-height: 220px;
  overflow-y: auto;
}

.ta-menu li {
  padding: 0.3rem 0.5rem;
  font-size: 0.65rem;
  color: #444;
  cursor: pointer;
  white-space: nowrap;
}
.ta-menu li:hover { background: #f0f0f0; color: var(--ink); }

/* active filter chips */
.chips { padding-top: 0.4rem; padding-bottom: 0.4rem; }

.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.18rem 0.5rem;
  font-size: 0.6rem;
  background: var(--ink);
  color: #fff;
  border-radius: 2px;
}
.chip.style { background: #444; }

.chip-clear {
  background: none;
  border: none;
  color: #aaa;
  cursor: pointer;
  padding: 0;
  font-size: 0.55rem;
  line-height: 1;
}
.chip-clear:hover { color: #fff; }

.error-banner {
  padding: 0.5rem 1.5rem;
  font-size: 0.65rem;
  color: #c44;
  background: #fff8f8;
  border-bottom: 1px solid #fde;
}

.sentinel { height: 1px; }
</style>
