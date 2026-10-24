<script setup lang="ts">
import type { Release } from '~/utils/release'

// The player fixed to the bottom of the screen while something is playing,
// for both store audio and discogs videos. Also hosts the offscreen YouTube
// iframe, which has to stay in the DOM across page changes

const { isLiked, toggleLike } = useLikes()
const {
  activeRelease, activeTrack, isPlaying, mode,
  currentTime, duration, volume,
  getItems, itemName, playAudio, playVideo, togglePlay, seek, setVolume,
  prevTrack, nextTrack, canPrev, canNext,
} = usePlayer()

const trackListOpen = ref(false)
const volOpen       = ref(false)

watch(activeRelease, () => { trackListOpen.value = false })

const isVideo = computed(() => mode.value === 'video')

// discogs titles are "Artist - Title", store releases have them separate
const heading = computed(() => {
  const r = activeRelease.value
  if (!r) return { artist: '', title: '' }
  return isVideo.value ? parseTitle(r.title) : { artist: r.artist || '', title: r.title || '' }
})

const art = computed(() => {
  const r = activeRelease.value
  if (!r) return FALLBACK_ART
  return (isVideo.value ? r.cover_image || r.thumb : artworkUrl(r)) || FALLBACK_ART
})

const items     = computed(() => activeRelease.value ? getItems(activeRelease.value) : [])
const videoLink = computed(() => isVideo.value ? activeRelease.value?.videos?.[activeTrack.value]?.uri : undefined)

const volumeIcon = computed(() =>
  volume.value === 0 ? ICON.volumeOff : volume.value < 0.5 ? ICON.volumeDown : ICON.volumeUp)

function pick(release: Release, idx: number) {
  if (isVideo.value) playVideo(release, idx)
  else playAudio(release, idx)
  trackListOpen.value = false
}

function onArtError(e: Event) {
  (e.target as HTMLImageElement).src = FALLBACK_ART
}

function rangeValue(e: Event): number {
  return +(e.target as HTMLInputElement).value
}
</script>

<template>
  <div>
    <div class="yt-offscreen"><div id="yt-iframe" /></div>

    <div v-if="activeRelease" class="player" @click.self="trackListOpen = false">

      <!-- track list drop-up -->
      <Transition name="slide-up">
        <div v-if="trackListOpen" class="track-list">
          <div
            v-for="(_, idx) in items"
            :key="idx"
            class="track-item"
            :class="{ active: idx === activeTrack }"
            @click="pick(activeRelease, idx)"
          >
            <span class="track-num">{{ idx + 1 }}</span>
            <span class="track-name">{{ itemName(activeRelease, idx) }}</span>
            <span v-if="idx === activeTrack && isPlaying" class="track-playing">&#9654;</span>
          </div>
        </div>
      </Transition>

      <div class="main">
        <img :src="art" class="art" @error="onArtError">

        <div class="info" @click="trackListOpen = !trackListOpen">
          <span class="artist">{{ heading.artist }}</span>
          <span class="title">{{ heading.title }}</span>
          <span class="track">
            {{ itemName(activeRelease, activeTrack) }}
            <span v-if="items.length > 1" class="chevron">{{ trackListOpen ? '&#9662;' : '&#9652;' }}</span>
          </span>
        </div>

        <template v-if="!isVideo">
          <div class="links">
            <button class="ctl like-btn" @click.stop="toggleLike(activeRelease)">
              <span class="fa">{{ isLiked(activeRelease.id) ? ICON.heart : ICON.heartOutline }}</span>
            </button>
            <button class="ctl" @click.stop="openLink(activeRelease.link)">
              <span class="fa">{{ isPreorder(activeRelease) ? ICON.calendar : ICON.cart }}</span>
            </button>
          </div>

          <div class="scrub-wrap">
            <span class="time">{{ formatTime(currentTime) }}</span>
            <input
              class="scrub"
              type="range"
              min="0"
              :max="duration || 100"
              :value="currentTime"
              :disabled="!duration"
              @input="seek(rangeValue($event))"
            >
            <span class="time">{{ formatTime(duration) }}</span>
          </div>

          <div class="vol-wrap">
            <button class="ctl vol-btn" @click.stop="volOpen = !volOpen">
              <span class="fa">{{ volumeIcon }}</span>
            </button>
            <div v-if="volOpen" class="vol-popout" @click.stop>
              <input
                class="vol-slider"
                type="range" min="0" max="1" step="0.01"
                :value="volume"
                @input="setVolume(rangeValue($event))"
              >
            </div>
          </div>
        </template>

        <template v-else>
          <div class="spacer" />
          <a
            v-if="videoLink"
            :href="videoLink"
            target="_blank"
            rel="noopener noreferrer"
            class="ctl yt-link"
            @click.stop
          ><span class="fa">{{ ICON.youtube }}</span></a>
        </template>

        <div class="controls">
          <button class="ctl" :disabled="!canPrev" @click="prevTrack">&#8249;</button>
          <button class="ctl play-btn" @click="togglePlay">
            <span v-if="isPlaying">&#9646;&#9646;</span>
            <span v-else>&#9654;</span>
          </button>
          <button class="ctl" :disabled="!canNext" @click="nextTrack">&#8250;</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.yt-offscreen {
  position: fixed;
  left: -200px;
  bottom: 0;
  width: 160px;
  height: 90px;
  overflow: hidden;
  pointer-events: none;
}

.player {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 200;
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border-top: 1px solid var(--line);
  box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.06);
}

.main {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.4rem 1rem 0.5rem;
}

.art {
  width: 36px;
  height: 36px;
  object-fit: cover;
  flex-shrink: 0;
}

/* ── Release info ── */

.info {
  flex: 0 1 auto;    /* as wide as the text */
  max-width: 28%;    /* long titles still truncate here */
  min-width: 60px;
  display: flex;
  flex-direction: column;
  gap: 1px;
  overflow: hidden;
  cursor: pointer;
  user-select: none;
}
.info:hover .chevron { opacity: 1; }

.artist, .title, .track {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.artist { font-size: 0.65rem; color: var(--ink); }
.title  { font-size: 0.58rem; color: #888; }
.track  { font-size: 0.55rem; color: var(--accent); }

.chevron {
  font-size: 0.45rem;
  opacity: 0.5;
  margin-left: 2px;
}

/* ── Buttons ── */

.links {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  flex-shrink: 0;    /* the icons never get squashed by a long title */
}

.controls {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  flex-shrink: 0;
}

.ctl {
  background: none;
  border: none;
  font-size: 1.2rem;
  color: #aaa;
  cursor: pointer;
  padding: 0.2rem 0.35rem;
  line-height: 1;
  transition: color 0.1s;
  text-decoration: none;
}
.ctl:not(:disabled):hover { color: #333; }
.ctl:disabled { opacity: 0.25; cursor: default; }

.like-btn:not(:disabled):hover { color: var(--like); }

.play-btn {
  font-size: 1rem;
  color: var(--ink);
  padding: 0.2rem 0.5rem;
}
.play-btn:not(:disabled):hover { color: var(--accent); }

.yt-link { font-size: 0.85rem; }

/* ── Scrub bar ── */

.scrub-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 0.35rem;
  min-width: 0;
}

.spacer { flex: 1; }

.time {
  font-size: 0.48rem;
  color: #bbb;
  flex-shrink: 0;
  min-width: 2.4ch;
  font-variant-numeric: tabular-nums;
}
.time:last-child { text-align: right; }

.scrub {
  flex: 1;
  min-width: 0;
  height: 3px;
  accent-color: var(--accent);
  cursor: pointer;
}
.scrub:disabled { opacity: 0.3; cursor: default; }

/* ── Volume ── */

.vol-wrap {
  position: relative;
  flex-shrink: 0;
}

.vol-btn {
  font-size: 0.8rem;
  padding: 0.2rem 0.3rem;
}

.vol-popout {
  position: absolute;
  bottom: calc(100% + 6px);
  right: 0;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 0.5rem 0.6rem;
  box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.08);
  display: flex;
  align-items: center;
}

.vol-slider {
  width: 80px;
  height: 3px;
  accent-color: var(--accent);
  cursor: pointer;
}

/* ── Track list ── */

.track-list {
  border-top: 1px solid #f0f0f0;
  max-height: 220px;
  overflow-y: auto;
  background: var(--panel);
}

.track-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 1rem;
  cursor: pointer;
  transition: background 0.1s;
  font-size: 0.6rem;
}
.track-item:hover  { background: #f7f7f7; }
.track-item.active { color: var(--accent); }

.track-num {
  color: #ccc;
  width: 1.5ch;
  flex-shrink: 0;
  text-align: right;
}
.track-item.active .track-num { color: var(--accent); }

.track-name {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.track-playing {
  font-size: 0.45rem;
  color: var(--accent);
  flex-shrink: 0;
}

.slide-up-enter-active,
.slide-up-leave-active { transition: max-height 0.2s ease, opacity 0.15s ease; overflow: hidden; }
.slide-up-enter-from,
.slide-up-leave-to     { max-height: 0; opacity: 0; }
.slide-up-enter-to,
.slide-up-leave-from   { max-height: 220px; opacity: 1; }
</style>
