<script setup lang="ts">
// The layout every release tile shares: catalogue line, artwork, artist /
// title, an icons row and the track dots. Purely presentational — it knows
// nothing about stores, discogs or the player, the wrapping tile
// (ReleaseTile, DiscogsTile) feeds it props and handles its events.
//
//   slots:  actions  icons on the left of the icons row (like, buy...)
//           badges   icons on the right of the icons row
//           default  anything extra at the bottom
//   events: play         the tile was clicked
//           select(idx)  a track dot was clicked
//           prev / next  arrow buttons, or a horizontal swipe on mobile
//           artist / sub the artist or sub line was clicked (when *Clickable)

const props = withDefaults(defineProps<{
  cat?: string
  art?: string | null
  artist?: string
  title?: string
  sub?: string               // extra line under the title (store, label)
  artistClickable?: boolean
  subClickable?: boolean
  trackCount: number
  active: boolean            // this tile's release is the one in the player
  activeTrack?: number
  playing?: boolean
  trackName?: string         // shown under the dots while active
  noTracksLabel?: string
  pending?: boolean          // tracks not known yet, show an ellipsis
}>(), {
  cat: '',
  art: null,
  artist: '',
  title: '',
  sub: '',
  activeTrack: 0,
  trackName: '',
  noTracksLabel: 'no audio',
})

const emit = defineEmits<{
  play: []
  select: [idx: number]
  prev: []
  next: []
  artist: []
  sub: []
}>()

// clickable text lines don't also start the tile playing
function onArtistClick(e: MouseEvent) {
  if (!props.artistClickable) return
  e.stopPropagation()
  emit('artist')
}

function onSubClick(e: MouseEvent) {
  if (!props.subClickable) return
  e.stopPropagation()
  emit('sub')
}

function onArtError(e: Event) {
  (e.target as HTMLImageElement).src = FALLBACK_ART
}

// ── Dots ─────────────────────────────────────────────────────────────────────

// up to five dots. with more tracks than that the window slides to keep the
// selected one in view, and a small dot at either end shows there's more
const MAX_DOTS = 5

interface Dot { index: number, small: boolean, selected: boolean }

const dots = computed<Dot[]>(() => {
  const n = props.trackCount
  const s = props.active ? props.activeTrack : -1
  if (n <= MAX_DOTS) {
    return Array.from({ length: n }, (_, i) => ({ index: i, small: false, selected: i === s }))
  }
  const half = Math.floor(MAX_DOTS / 2)
  let start  = s - half
  let end    = start + MAX_DOTS - 1
  if (start < 0) { start = 0;   end = MAX_DOTS - 1 }
  if (end >= n)  { end = n - 1; start = n - MAX_DOTS }
  return Array.from({ length: MAX_DOTS }, (_, i) => {
    const idx  = start + i
    const more = (start > 0 && i === 0) || (end < n - 1 && i === MAX_DOTS - 1)
    return more
      ? { index: -1, small: true, selected: false }
      : { index: idx, small: false, selected: idx === s }
  })
})

function onDot(dot: Dot) {
  if (dot.index >= 0) emit('select', dot.index)
}

// ── Swipe (mobile track change) ──────────────────────────────────────────────

let swipeStartX = 0
let swipeStartY = 0
const swipeDir  = ref<-1 | 0 | 1>(0)

function onSwipeStart(e: TouchEvent) {
  swipeStartX    = e.touches[0]!.clientX
  swipeStartY    = e.touches[0]!.clientY
  swipeDir.value = 0
}

function onSwipeEnd(e: TouchEvent) {
  const dx = e.changedTouches[0]!.clientX - swipeStartX
  const dy = e.changedTouches[0]!.clientY - swipeStartY
  if (!props.active || Math.abs(dx) < 40 || Math.abs(dx) < Math.abs(dy)) return
  swipeDir.value = dx < 0 ? -1 : 1
  if (dx < 0) emit('next')
  else emit('prev')
}

const artClass = computed(() => {
  if (!props.active || !swipeDir.value) return ''
  return swipeDir.value < 0 ? 'slide-left' : 'slide-right'
})
</script>

<template>
  <div
    class="tile"
    :class="{ active, 'no-tracks': !trackCount }"
    @click="trackCount && emit('play')"
    @touchstart.passive="onSwipeStart"
    @touchend.passive="onSwipeEnd"
  >
    <p class="r-cat">{{ cat }}</p>
    <div class="artwork-wrap">
      <!-- keyed on the track so the slide animation replays on each swipe -->
      <img
        :key="active ? activeTrack : -1"
        :src="art || FALLBACK_ART"
        :alt="title"
        class="tile-art"
        :class="artClass"
        @error="onArtError"
      >
    </div>
    <p
      class="r-artist"
      :class="{ clickable: artistClickable }"
      @click="onArtistClick"
    >{{ artist }}</p>
    <p class="r-title">{{ title }}</p>
    <p
      v-if="sub"
      class="r-sub"
      :class="{ clickable: subClickable }"
      @click="onSubClick"
    >{{ sub }}</p>

    <div class="icons-row">
      <div class="icons-group"><slot name="actions" /></div>
      <div class="icons-group badges"><slot name="badges" /></div>
    </div>

    <div v-if="trackCount" class="dots-row">
      <button
        v-if="active && trackCount > 1"
        class="nav-btn"
        :disabled="activeTrack === 0"
        @click.stop="emit('prev')"
      >&#8249;</button>

      <svg :width="dots.length * 12" height="12">
        <g v-for="(dot, i) in dots" :key="i" class="dot" @click.stop="onDot(dot)">
          <circle v-if="dot.small" :cx="i * 12 + 6" cy="6" r="1.5" class="dot-more" />
          <polygon v-else-if="dot.selected && playing" :points="`${i * 12 + 4},3 ${i * 12 + 4},9 ${i * 12 + 9},6`" class="dot-selected" />
          <circle v-else-if="dot.selected" :cx="i * 12 + 6" cy="6" r="3.5" class="dot-selected" />
          <circle v-else :cx="i * 12 + 6" cy="6" r="2.5" class="dot-idle" />
        </g>
      </svg>

      <button
        v-if="active && trackCount > 1"
        class="nav-btn"
        :disabled="activeTrack === trackCount - 1"
        @click.stop="emit('next')"
      >&#8250;</button>
    </div>
    <div v-else class="dots-row">
      <span v-if="pending" class="no-tracks-label pending">...</span>
      <span v-else class="no-tracks-label">{{ noTracksLabel }}</span>
    </div>

    <div class="r-trackname-wrap">
      <span v-if="active" :key="trackName" class="r-trackname">{{ trackName }}</span>
    </div>

    <slot />
  </div>
</template>

<style scoped>
.tile {
  width: 150px;
  cursor: pointer;
}
.tile.no-tracks { cursor: default; }

/* ── Artwork ── */

.artwork-wrap {
  overflow: hidden;
  width: 150px;
  height: 150px;
}

.tile-art {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.tile-art.slide-left  { animation: slide-in-left  0.25s ease-out; }
.tile-art.slide-right { animation: slide-in-right 0.25s ease-out; }

@keyframes slide-in-left  { from { transform: translateX(100%);  } to { transform: translateX(0); } }
@keyframes slide-in-right { from { transform: translateX(-100%); } to { transform: translateX(0); } }

/* ── Text lines ── */

.r-cat, .r-artist, .r-title, .r-sub {
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-height: 1em;
}

.r-cat    { font-size: 0.55rem; color: #bbb; margin-bottom: 2px; }
.r-artist { font-size: 0.65rem; color: var(--ink); margin: 3px 0 1px; }
.r-title  { font-size: 0.6rem;  color: #888; }
.r-sub    { font-size: 0.55rem; color: #bbb; margin-top: 1px; }

.clickable { cursor: pointer; }
.clickable:hover { text-decoration: underline dotted; }

/* ── Icons row ── */

.icons-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 4px;
  height: 16px;
}

.icons-group {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 0.75rem;
}
.icons-group.badges { gap: 3px; font-size: 0.7rem; }

/* ── Dots ── */

.dots-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  margin-top: 2px;
  height: 16px;
}

.dot { cursor: pointer; }
.dot-more     { fill: #bbb; opacity: 0.4; }
.dot-selected { fill: var(--accent); }
.dot-idle     { fill: #ccc; opacity: 0.35; }
.tile.active .dot-idle { fill: #999; opacity: 1; }

.nav-btn {
  background: none;
  border: none;
  font-size: 1rem;
  color: #aaa;
  cursor: pointer;
  padding: 0;
  line-height: 1;
  transition: color 0.1s;
}
.nav-btn:not(:disabled):hover { color: #333; }
.nav-btn:disabled { opacity: 0.25; cursor: default; }

.no-tracks-label {
  font-size: 0.5rem;
  color: #ddd;
  letter-spacing: 0.05em;
}

.pending {
  display: inline-block;
  overflow: hidden;
  white-space: nowrap;
  animation: dotgrow 1.5s steps(3, end) infinite;
}

@keyframes dotgrow {
  from { max-width: 1ch; }
  to   { max-width: 4ch; }
}

/* ── Track name marquee ── */

.r-trackname-wrap {
  overflow: hidden;
  text-align: center;
  margin-top: 3px;
  min-height: 1em;
}

.r-trackname {
  display: inline-block;
  font-size: 0.58rem;
  color: var(--accent);
  white-space: nowrap;
  animation: trackscroll 7s ease-in-out infinite;
}

/* scroll a name wider than the tile across and back */
@keyframes trackscroll {
  0%,  20% { transform: translateX(0); }
  80%, 100% { transform: translateX(min(0px, calc(150px - 100%))); }
}

/* full width tiles on mobile */
@media (max-width: 600px) {
  .tile { width: 100%; }
  .artwork-wrap { width: 100%; height: auto; aspect-ratio: 1; }

  @keyframes trackscroll {
    0%,  20% { transform: translateX(0); }
    80%, 100% { transform: translateX(min(0px, calc(100vw - 3rem - 100%))); }
  }
}
</style>
