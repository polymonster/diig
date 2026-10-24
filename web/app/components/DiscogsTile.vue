<script setup lang="ts">
import type { Release, Video } from '~/utils/release'
import type { DiscogsResult, DiscogsDetails } from '~/composables/useDiscogs'

// A discogs search result tile: plays the release's YouTube videos, links out
// to discogs. The artist and label lines filter the results
const props = defineProps<{
  item: DiscogsResult
  details: DiscogsDetails | null | undefined   // undefined: not fetched yet, null: in flight
}>()

const emit = defineEmits<{
  artist: [name: string]
  label: [name: string]
}>()

const { activeTrack, isPlaying, isActive, toggleRelease, playVideo, prevTrack, nextTrack } = usePlayer()

// the result as something the player can play: its videos come from the
// separately fetched details
const release = computed<Release>(() => ({
  ...props.item,
  id:     String(props.item.id),
  videos: props.details?.videos ?? [],
}))

const videos = computed<Video[]>(() => release.value.videos!)
const parsed = computed(() => parseTitle(props.item.title))
const label  = computed(() => props.details?.labels?.[0]?.name ?? '')
const active = computed(() => isActive(release.value))

function openOnDiscogs() {
  openLink(`https://www.discogs.com${props.item.uri}`)
}
</script>

<template>
  <TileBase
    :cat="item.catno || (item.format || []).join(', ')"
    :art="item.cover_image || item.thumb"
    :artist="parsed.artist || item.title"
    :title="parsed.artist ? parsed.title : ''"
    :artist-clickable="!!parsed.artist"
    :sub="label"
    sub-clickable
    :track-count="videos.length"
    :active="active"
    :active-track="activeTrack"
    :playing="isPlaying"
    :track-name="videos[activeTrack]?.title"
    no-tracks-label="no video"
    :pending="!details"
    @play="toggleRelease(release, 'video')"
    @select="idx => playVideo(release, idx)"
    @prev="prevTrack"
    @next="nextTrack"
    @artist="emit('artist', parsed.artist)"
    @sub="emit('label', label)"
  >
    <template #actions>
      <button class="icon-btn" title="Open on Discogs" @click.stop="openOnDiscogs">
        <span class="fa">{{ ICON.globe }}</span>
      </button>
    </template>
    <template #badges>
      <span class="year">{{ item.year || '' }}</span>
    </template>
  </TileBase>
</template>

<style scoped>
.icon-btn:hover { color: #333; }

.year {
  font-size: 0.55rem;
  color: #bbb;
  letter-spacing: 0.02em;
}
</style>
