<script setup>
const menuOpen = useState('menuOpen', () => false)

// Faster cadence than the site-wide nav badge — on this page the offline→live
// flip should feel immediate.
const { isLive, checking, meta, configured, iframeUrl } = useLiveStatus(10_000)

// Don't talk over the mix: kill any snippet or Discogs clip still going in the
// bottom player bar.
const { stopAll } = usePlayer()
onMounted(stopAll)

watch(isLive, live => { if (live) stopAll() })
</script>

<template>
  <div class="page">
    <header class="header">
      <NuxtLink to="/" class="logo">diig</NuxtLink>
      <span class="page-title">live</span>
      <div class="header-right">
        <NuxtLink to="/likes" class="likes-nav">
          <span class="fa">&#xf004;</span>
        </NuxtLink>
        <button class="burger-btn fa" @click="menuOpen = !menuOpen">&#xf0c9;</button>
      </div>
    </header>

    <div v-if="checking" class="loading">
      <img src="/spinner.png" class="spinner" alt="loading" >
    </div>

    <main v-else class="content">
      <template v-if="isLive">
        <div class="stage">
          <iframe
            :src="iframeUrl"
            class="stream"
            title="diig live"
            allow="accelerometer; gyroscope; autoplay; encrypted-media; picture-in-picture"
            allowfullscreen
          />
        </div>

        <div class="now">
          <span class="live-dot" />
          <span class="live-label">live</span>
          <span v-if="meta?.artist" class="now-artist">{{ meta.artist }}</span>
          <span v-if="meta?.title" class="now-title">{{ meta.title }}</span>
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

.page { min-height: 100vh; background: #f5f5f5; color: #0a0a0a; }

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
  text-decoration: none;
  color: #0a0a0a;
}

.page-title {
  font-size: 0.8rem;
  color: #999;
}

.header-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.9rem;
}

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

.stage {
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #0a0a0a;
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

.live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #cc4d00;
  flex: 0 0 7px;
  animation: pulse 1.6s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.25; }
}

.live-label {
  font-size: 0.6rem;
  letter-spacing: 0.12em;
  color: #cc4d00;
  text-transform: uppercase;
}

.now-artist {
  font-size: 0.7rem;
  color: #0a0a0a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.now-title {
  font-size: 0.65rem;
  color: #888;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.offline {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  min-height: 50vh;
  border: 1px solid #e0e0e0;
  background: #fff;
}

.offline-head {
  margin: 0;
  font-size: 0.8rem;
  color: #bbb;
  letter-spacing: 0.05em;
}

.offline-next {
  margin: 0;
  font-size: 0.65rem;
  color: #cc4d00;
}

@media (max-width: 600px) {
  .content { padding: 0.75rem; }
  .header  { gap: 1rem; }
}
</style>
