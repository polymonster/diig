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
  { id: 'new_releases', label: 'New' },
  { id: 'chart',        label: 'Hot' },
]

const selectedView   = ref(localStorage.getItem('diig_view') || 'new_releases')
const sectionReleases = ref({})
const loading        = ref(false)

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
  const t   = triplet(store, section, viewId)
  try {
    const token = await auth.currentUser.getIdToken()
    const url   = `${DB}/releases.json?orderBy="${t}"&startAt=0&auth=${token}`
    const data  = await fetch(url).then(r => r.json())
    if (!data || typeof data !== 'object') { sectionReleases.value[key] = []; return }
    const items = Object.entries(data).map(([id, v]) => ({ id, ...v }))
    items.sort((a, b) => (a[t] ?? 999) - (b[t] ?? 999))
    sectionReleases.value[key] = items.slice(0, 32)
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

watch(user, u => { if (u) { loadAll(); loadLikes() } }, { immediate: true })

function selectView(viewId) {
  stopAll()
  selectedView.value = viewId
  localStorage.setItem('diig_view', viewId)
  loadAll()
}


const releasesByStore = computed(() =>
  STORES.map(store => {
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

// ── Likes ─────────────────────────────────────────────────────────────────────

const likes           = ref({})  // id -> timestamp
const likeCountAdjust = ref({})  // id -> delta on top of server count

function isLiked(id) { return id in likes.value }

function likeCount(release) {
  return Math.max(0, (release.likes?.count ?? 0) + (likeCountAdjust.value[release.id] ?? 0))
}

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

const { activeId, activeTrack, isPlaying, releaseList, tileClick, setTrack, prevTrack, nextTrack, dotClick, computeDots, getTracks, getTrackNames, stopAll } = useAudio()

watch(releasesByStore, val => {
  releaseList.value = val.flatMap(({ releases }) => releases)
})

// ── Swipe (mobile track change) ───────────────────────────────────────────────

let swipeStartX = 0
let swipeStartY = 0

function onSwipeStart(e) {
  swipeStartX = e.touches[0].clientX
  swipeStartY = e.touches[0].clientY
}

function onSwipeEnd(release, e) {
  const dx = e.changedTouches[0].clientX - swipeStartX
  const dy = e.changedTouches[0].clientY - swipeStartY
  if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) {
    dx < 0 ? nextTrack(release, e) : prevTrack(release, e)
  }
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
        <NuxtLink to="/stores"  class="viewbtn stores-link">Stores &rsaquo;</NuxtLink>
        <NuxtLink to="/discogs" class="viewbtn stores-link">Discogs &rsaquo;</NuxtLink>
      </nav>
      <div class="header-right">
        <NuxtLink to="/chat" class="chat-nav">
          <span class="fa">&#xf086;</span>
        </NuxtLink>
        <NuxtLink to="/likes" class="likes-nav">
          <span class="fa">&#xf004;</span>
        </NuxtLink>
        <button class="burger-btn fa" @click="menuOpen = !menuOpen">&#xf0c9;</button>
      </div>
    </header>

    <div v-if="loading" class="loading">
      <img src="/spinner.png" class="spinner" alt="loading" />
    </div>

    <main v-else class="content">
      <div v-for="{ store, releases } in releasesByStore" :key="store.id" class="store-block">
        <h2 class="store-name">
          <NuxtLink :to="`/store/${store.id}`" class="store-link">{{ store.name }}</NuxtLink>
        </h2>
        <div class="tile-row">
          <div
            v-for="release in releases"
            :key="release.id"
            class="tile"
            :class="{ active: activeId === release.id, 'no-audio': !getTracks(release).length }"
            @click="getTracks(release).length && tileClick(release)"
            @touchstart.passive="onSwipeStart"
            @touchend.passive="onSwipeEnd(release, $event)"
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

              <!-- like + buy left, hype right -->
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

.chat-nav {
  font-size: 1rem;
  color: #ccc;
  text-decoration: none;
  transition: color 0.15s;
}
.chat-nav:hover { color: #555; }

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

@keyframes spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

.content {
  max-width: 1400px;
  margin: 0 auto;
  padding: 1.5rem;
}

.store-block { margin-bottom: 2rem; }

.store-name {
  font-size: 0.7rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  margin: 0 0 0.75rem;
}

.store-link {
  color: #999;
  text-decoration: none;
  transition: color 0.15s;
}
.store-link:hover { color: #0a0a0a; }

.tile-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tile {
  width: 150px;
  flex: 0 0 150px;
  cursor: pointer;
}

.tile.no-audio { cursor: default; }

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
  .tile     { width: 100%; flex: 0 0 100%; }
  .tile-art { width: 100%; height: auto; aspect-ratio: 1; }
  @keyframes trackscroll {
    0%,  20% { transform: translateX(0); }
    80%, 100% { transform: translateX(min(0px, calc(100vw - 3rem - 100%))); }
  }
}

.dots-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  margin-top: 2px;
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

/* Icons row */
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
  gap: 2px;
  color: #bbb;
  font-size: 0.75rem;
  line-height: 1;
  transition: color 0.15s;
  text-decoration: none;
}

.like-btn:hover     { color: #e03070; }
.like-btn.liked     { color: #e03070; }
.like-count {
  font-family: 'Cousine', monospace;
  font-size: 0.55rem;
  color: inherit;
}

.buy-btn:hover      { color: #333; }
.buy-btn.preorder   { color: #7a8a99; }
.buy-btn.sold       { color: #ccc; opacity: 0.4; }

.hype-icons {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 0.7rem;
}

.hype.fire   { color: #cc4d00; }
.hype.thermo { color: #e09000; }
.hype.excl   { color: #aaa; }

.empty {
  font-size: 0.75rem;
  color: #bbb;
  padding: 0.5rem 0;
  margin: 0;
}
</style>
