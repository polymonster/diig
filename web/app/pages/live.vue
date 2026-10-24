<script setup lang="ts">
// The live stream, or the last recorded mix while offline. Public, so a
// broadcast link can be shared with anyone

// faster cadence than the header badge, here the offline → live flip should
// feel immediate
const { isLive, checking, meta, configured, iframeUrl, recordingUrl } = useLiveStatus(10_000)

// don't talk over the mix: stop any snippet or discogs clip in the player bar
const { stopAll } = usePlayer()
onMounted(stopAll)
watch(isLive, live => { if (live) stopAll() })

const STREAM_ALLOW = 'accelerometer; gyroscope; autoplay; encrypted-media; picture-in-picture'
</script>

<template>
  <div class="page">
    <AppHeader>
      <span class="page-title">live</span>
    </AppHeader>

    <LoadingSpinner v-if="checking" full />

    <main v-else class="content">
      <template v-if="isLive">
        <div class="stage">
          <iframe :src="iframeUrl" class="stream" title="diig live" :allow="STREAM_ALLOW" allowfullscreen />
        </div>
        <div class="now">
          <span class="live-dot" />
          <span class="label live">live</span>
          <span v-if="meta?.artist" class="now-artist">{{ meta.artist }}</span>
          <span v-if="meta?.title" class="now-title">{{ meta.title }}</span>
        </div>
      </template>

      <template v-else-if="recordingUrl">
        <div class="stage">
          <iframe :src="recordingUrl" class="stream" title="diig last mix" :allow="STREAM_ALLOW" allowfullscreen />
        </div>
        <div class="now">
          <span class="label">{{ meta?.lastTitle || 'last mix' }}</span>
          <span v-if="meta?.next" class="now-title">next &mdash; {{ meta.next }}</span>
        </div>
      </template>

      <div v-else class="offline">
        <p class="offline-head">no mix right now</p>
        <p v-if="meta?.next" class="offline-next">next &mdash; {{ meta.next }}</p>
        <p v-else-if="!configured" class="offline-next">stream not configured</p>
      </div>
    </main>
  </div>
</template>

<style scoped>
.stage {
  width: 100%;
  aspect-ratio: 16 / 9;
  background: var(--ink);
}

.stream {
  width: 100%;
  height: 100%;
  border: none;
  display: block;
}

.now {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-top: 0.7rem;
  min-height: 1rem;
}

.label {
  font-size: 0.6rem;
  letter-spacing: 0.12em;
  color: #999;
  text-transform: uppercase;
}
.label.live { color: var(--accent); }

.now-artist,
.now-title {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.now-artist { font-size: 0.7rem;  color: var(--ink); }
.now-title  { font-size: 0.65rem; color: #888; }

.offline {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  min-height: 50vh;
  border: 1px solid var(--line);
  background: var(--panel);
}

.offline-head {
  font-size: 0.8rem;
  color: #bbb;
  letter-spacing: 0.05em;
}

.offline-next {
  font-size: 0.65rem;
  color: var(--accent);
}

@media (max-width: 600px) {
  .content { padding: 0.75rem; }
}
</style>
