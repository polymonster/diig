<script setup>
// a single release tile: artwork, like / buy / hype icons and the track player
// dots. shared by the store shelves (index) and the weekly homepage
const props = defineProps({
  release: { type: Object, required: true },
})

const { isLiked, toggleLike } = useLikes()
const { activeId, activeTrack, isPlaying, tileClickAudio: tileClick, prevTrack, nextTrack, dotClick, computeDots, getTracks, getTrackNames } = usePlayer()

// ── Swipe (mobile track change) ───────────────────────────────────────────────

let swipeStartX = 0
let swipeStartY = 0
const swipeDir = ref(0)

function onSwipeStart(e) {
  swipeStartX = e.touches[0].clientX
  swipeStartY = e.touches[0].clientY
  swipeDir.value = 0
}

function onSwipeEnd(e) {
  const dx = e.changedTouches[0].clientX - swipeStartX
  const dy = e.changedTouches[0].clientY - swipeStartY
  if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) {
    swipeDir.value = dx < 0 ? -1 : 1
    dx < 0 ? nextTrack(e) : prevTrack(e)
  }
}

const release = computed(() => props.release)
</script>

<template>
  <div
    class="tile"
    :class="{ active: activeId === release.id, 'no-audio': !getTracks(release).length }"
    :data-release-id="release.id"
    @click="getTracks(release).length && tileClick(release)"
    @touchstart.passive="onSwipeStart"
    @touchend.passive="onSwipeEnd"
  >
    <p v-if="labelCat(release)" class="r-cat">{{ labelCat(release) }}</p>
    <div class="artwork-wrap">
      <img
        :key="activeId === release.id ? `art-${release.id}-${activeTrack}` : `art-${release.id}`"
        :src="artworkUrl(release) || '/white_label.jpg'"
        :alt="release.title"
        class="tile-art"
        :class="activeId === release.id && swipeDir !== 0 ? (swipeDir < 0 ? 'slide-left' : 'slide-right') : ''"
        @error="e => e.target.src = '/white_label.jpg'"
      />
    </div>
    <p class="r-artist">{{ release.artist }}</p>
    <p class="r-title">{{ release.title || ' ' }}</p>

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
          :class="{ preorder: isPreorder(release), sold: isSoldOut(release) }"
          @click.stop
        >
          <span v-if="isPreorder(release)" class="fa">&#xf271;</span><span v-else class="fa">&#xf07a;</span>
        </a>
        <span v-if="isSoldOut(release)" class="fa sold-excl" title="Sold out">&#xf12a;</span>
      </div>
      <div class="hype-icons">
        <span v-if="hasCharted(release)"    class="fa hype fire"   title="Charted">&#xf06d;</span>
        <span v-if="isLowStock(release)"    class="fa hype thermo" title="Low stock">&#xf2ca;</span>
        <span v-if="isBackInStock(release)" class="fa hype excl"   title="Back in stock">&#xf12a;</span>
      </div>
    </div>

    <div v-if="getTracks(release).length" class="dots-row">
      <button
        v-if="activeId === release.id && getTracks(release).length > 1"
        class="nav-btn"
        :disabled="activeTrack === 0"
        @click="prevTrack($event)"
      >&#8249;</button>

      <template v-for="(dots, i) in [computeDots(getTracks(release).length, activeId === release.id ? activeTrack : -1)]" :key="i">
      <svg :width="dots.length * 12" height="12">
        <g
          v-for="(dot, i) in dots"
          :key="i"
          style="cursor:pointer"
          @click="dotClick(release, dot.index, $event)"
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
        @click="nextTrack($event)"
      >&#8250;</button>
    </div>
    <div v-else class="dots-row no-audio-row">
      <span class="no-audio-label">no audio</span>
    </div>

    <div class="r-trackname-wrap">
      <span class="r-trackname" :key="`${release.id}-${activeTrack}`">{{ activeId === release.id ? (getTrackNames(release)[activeTrack] || '') : '' }}</span>
    </div>

    <slot />
  </div>
</template>

<style scoped>
* { font-family: 'Cousine', monospace; box-sizing: border-box; }

.fa {
  font-family: 'FontAwesome';
  font-style: normal;
  font-weight: normal;
  line-height: 1;
  -webkit-font-smoothing: antialiased;
}

.tile {
  width: 150px;
  flex: 0 0 150px;
  cursor: pointer;
}

.tile.no-audio { cursor: default; }

.artwork-wrap {
  overflow: hidden;
  width: 150px;
  height: 150px;
}

.tile-art {
  width: 150px;
  height: 150px;
  object-fit: cover;
  display: block;
}

.tile-art.slide-left  { animation: slide-in-left  0.25s ease-out; }
.tile-art.slide-right { animation: slide-in-right 0.25s ease-out; }

@keyframes slide-in-left {
  from { transform: translateX(100%); }
  to   { transform: translateX(0); }
}

@keyframes slide-in-right {
  from { transform: translateX(-100%); }
  to   { transform: translateX(0); }
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
  min-height: 1em;
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

.buy-btn:hover      { color: #333; }
.buy-btn.preorder   { color: #7a8a99; }
.buy-btn.sold       { color: #bbb; }
.sold-excl          { color: #bbb; font-size: 0.75rem; line-height: 1; }

.hype-icons {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 0.7rem;
}

.hype.fire   { color: #cc4d00; }
.hype.thermo { color: #e09000; }
.hype.excl   { color: #aaa; }

@media (max-width: 600px) {
  .tile { width: 100%; }

  /* artwork: full-width on mobile */
  .artwork-wrap {
    width: 100%;
    height: auto;
    aspect-ratio: 1;
  }
  .tile-art {
    width: 100%;
    height: 100%;
    aspect-ratio: 1;
  }

  @keyframes trackscroll {
    0%,  20% { transform: translateX(0); }
    80%, 100% { transform: translateX(min(0px, calc(100vw - 3rem - 100%))); }
  }
}
</style>
