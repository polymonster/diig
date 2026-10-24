<script setup lang="ts">
import type { Release } from '~/utils/release'

// A store release tile: like / buy / stock icons, plays the store's audio
// snippets. Used on every page that lists store releases
const props = defineProps<{
  release: Release
  sub?: string   // optional extra line under the title
}>()

const { isLiked, toggleLike } = useLikes()
const { activeTrack, isPlaying, isActive, getTracks, getTrackNames, toggleRelease, playAudio, prevTrack, nextTrack } = usePlayer()

const active = computed(() => isActive(props.release))
</script>

<template>
  <TileBase
    :cat="labelCat(release)"
    :art="artworkUrl(release)"
    :artist="release.artist"
    :title="release.title"
    :sub="sub"
    :track-count="getTracks(release).length"
    :active="active"
    :active-track="activeTrack"
    :playing="isPlaying"
    :track-name="getTrackNames(release)[activeTrack]"
    :data-release-id="release.id"
    @play="toggleRelease(release, 'audio')"
    @select="idx => playAudio(release, idx)"
    @prev="prevTrack"
    @next="nextTrack"
  >
    <template #actions>
      <button class="icon-btn like-btn" :class="{ liked: isLiked(release.id) }" @click.stop="toggleLike(release)">
        <span class="fa">{{ isLiked(release.id) ? ICON.heart : ICON.heartOutline }}</span>
      </button>
      <a
        v-if="release.link"
        :href="release.link"
        target="_blank"
        class="icon-btn buy-btn"
        :class="{ preorder: isPreorder(release), sold: isSoldOut(release) }"
        @click.stop
      >
        <span class="fa">{{ isPreorder(release) ? ICON.calendar : ICON.cart }}</span>
      </a>
      <span v-if="isSoldOut(release)" class="fa sold" title="Sold out">{{ ICON.exclamation }}</span>
    </template>

    <template #badges>
      <span v-if="hasCharted(release)"    class="fa charted"  title="Charted">{{ ICON.fire }}</span>
      <span v-if="isLowStock(release)"    class="fa lowstock" title="Low stock">{{ ICON.thermometer }}</span>
      <span v-if="isBackInStock(release)" class="fa restock"  title="Back in stock">{{ ICON.exclamation }}</span>
    </template>

    <slot />
  </TileBase>
</template>

<style scoped>
.like-btn:hover,
.like-btn.liked   { color: var(--like); }

.buy-btn:hover    { color: #333; }
.buy-btn.preorder { color: #7a8a99; }
.buy-btn.sold     { color: #bbb; }

.sold     { color: #bbb; }
.charted  { color: var(--accent); }
.lowstock { color: #e09000; }
.restock  { color: #aaa; }
</style>
