<script setup>
import { useCurrentUser } from 'vuefire'

const user = useCurrentUser()
const { page, loading, loadHomepage } = useHomepage()

watch(user, u => { if (u) loadHomepage() }, { immediate: true })

const picks = computed(() => toArray(page.value?.picks))
const hype  = computed(() => toArray(page.value?.hype))
const gigs  = computed(() => toArray(page.value?.gigs))

function toArray(val) {
  if (!val) return []
  return Array.isArray(val) ? val : Object.values(val)
}

// ── Player ────────────────────────────────────────────────────────────────────

const menuOpen = useState('menuOpen', () => false)
const { isLive } = useLiveStatus()
const { releaseList, stopAll } = usePlayer()

watch([picks, hype], ([p, h]) => { releaseList.value = [...p, ...h] }, { immediate: true })
onUnmounted(stopAll)

function storeNames(release) {
  return toArray(release.stores).map(s => s.store)
}

function gigDate(gig) {
  const d = new Date(`${gig.date}T00:00:00`)
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
}
</script>

<template>
  <div class="page">
    <header class="header">
      <NuxtLink to="/" class="logo">diig</NuxtLink>
      <nav class="viewnav">
        <NuxtLink to="/"        class="viewbtn stores-link">&lsaquo; Shelves</NuxtLink>
        <span class="viewbtn active">Weekly</span>
      </nav>
      <div class="header-right">
        <NuxtLink v-if="isLive" to="/live" class="live-nav">
          <span class="live-nav-dot" />live
        </NuxtLink>
        <NuxtLink to="/likes" class="likes-nav">
          <span class="fa">&#xf004;</span>
        </NuxtLink>
        <button class="burger-btn fa" @click="menuOpen = !menuOpen">&#xf0c9;</button>
      </div>
    </header>

    <div v-if="loading && !page" class="loading">
      <img src="/spinner.png" class="spinner" alt="loading" />
    </div>

    <main v-else-if="page" class="content">
      <section class="intro">
        <p class="week">{{ page.week }}</p>
        <h1 class="headline">{{ page.headline }}</h1>
        <p class="intro-text">{{ page.intro }}</p>
      </section>

      <section v-if="picks.length" class="section">
        <h2 class="section-name">Picks</h2>
        <div class="picks">
          <div v-for="release in picks" :key="release.id" class="pick">
            <ReleaseTile :release="release" />
            <div class="pick-text">
              <p v-if="release.blurb" class="blurb">{{ release.blurb }}</p>
              <p class="shops">{{ storeNames(release).join(' · ') }}</p>
            </div>
          </div>
        </div>
      </section>

      <section v-if="hype.length" class="section">
        <div class="shelf">
          <!-- heading inside the grid, as on the store shelves, so it lines up with the first tile -->
          <h2 class="section-name shelf-name">Hype</h2>
          <div v-for="release in hype" :key="release.id">
            <ReleaseTile :release="release">
              <p class="shops tile-shops">
                <a
                  v-for="s in toArray(release.stores)"
                  :key="s.store"
                  :href="s.link"
                  target="_blank"
                  class="shop-link"
                  :class="{ sold: s.out_of_stock }"
                  @click.stop
                >{{ s.store }}</a>
              </p>
            </ReleaseTile>
          </div>
        </div>
      </section>

      <section v-if="gigs.length" class="section">
        <h2 class="section-name">London gigs</h2>
        <div class="gigs">
          <a v-for="gig in gigs" :key="gig.id" :href="gig.url" target="_blank" class="gig">
            <img v-if="gig.flyer" :src="gig.flyer" :alt="gig.title" class="gig-flyer" loading="lazy" />
            <div class="gig-text">
              <p class="gig-date">{{ gigDate(gig) }} · {{ gig.venue }}</p>
              <p class="gig-title">{{ gig.title }}</p>
              <p v-if="gig.blurb" class="blurb">{{ gig.blurb }}</p>
            </div>
          </a>
        </div>
      </section>
    </main>

    <main v-else class="content">
      <p class="empty">No weekly page yet.</p>
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
  color: inherit;
  text-decoration: none;
}

.viewnav {
  display: flex;
  gap: 0.25rem;
}

.viewbtn {
  padding: 0.35rem 0.9rem;
  font-size: 0.8rem;
  background: none;
  border: 1px solid transparent;
  color: #999;
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

.intro {
  max-width: 640px;
  margin: 0 auto 2rem;
}

.week {
  font-size: 0.6rem;
  letter-spacing: 0.15em;
  color: #bbb;
  margin: 0;
}

.headline {
  font-size: 1.2rem;
  font-weight: normal;
  margin: 0.25rem 0 0.5rem;
}

.intro-text {
  font-size: 0.75rem;
  color: #555;
  line-height: 1.5;
  margin: 0;
}

.section {
  margin-bottom: 2.5rem;
}

.section-name {
  font-size: 0.7rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: #999;
  font-weight: normal;
  margin: 0 0 0.75rem;
}

/* picks: tile with the blurb beside it */
.picks {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 1.25rem 2rem;
}

.pick {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
}

.pick-text {
  flex: 1;
  min-width: 0;
  padding-top: 1rem;
}

.blurb {
  font-size: 0.7rem;
  line-height: 1.5;
  color: #333;
  margin: 0 0 0.4rem;
}

.shops {
  font-size: 0.55rem;
  letter-spacing: 0.05em;
  color: #aaa;
  margin: 0;
}

/* hype: same shelf layout as a store section */
.shelf {
  display: grid;
  grid-template-columns: repeat(auto-fill, 150px);
  gap: 8px;
  justify-content: center;
}

.shelf-name {
  grid-column: 1 / -1;
  margin-bottom: 0.25rem;
}

.tile-shops {
  display: flex;
  flex-wrap: wrap;
  gap: 0 6px;
  margin-top: 2px;
}

.shop-link {
  color: #999;
  text-decoration: none;
}
.shop-link:hover { color: #0a0a0a; }
.shop-link.sold  { text-decoration: line-through; color: #ccc; }

/* gigs */
.gigs {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1rem;
}

.gig {
  display: flex;
  gap: 0.75rem;
  color: inherit;
  text-decoration: none;
  background: #fff;
  border: 1px solid #e8e8e8;
  padding: 0.6rem;
  transition: border-color 0.15s;
}
.gig:hover { border-color: #0a0a0a; }

.gig-flyer {
  width: 72px;
  height: 72px;
  object-fit: cover;
  flex: 0 0 72px;
}

.gig-text { min-width: 0; }

.gig-date {
  font-size: 0.55rem;
  letter-spacing: 0.05em;
  color: #cc4d00;
  margin: 0 0 2px;
}

.gig-title {
  font-size: 0.65rem;
  margin: 0 0 0.3rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty {
  font-size: 0.75rem;
  color: #bbb;
  text-align: center;
  padding: 3rem 0;
}

@media (max-width: 600px) {
  .header {
    flex-wrap: wrap;
    gap: 0;
    padding: 0.75rem 1rem 0;
  }
  .viewnav {
    order: 3;
    width: 100%;
    padding: 0.35rem 0;
    border-top: 1px solid #f0f0f0;
    margin-top: 0.5rem;
    gap: 0;
  }
  .viewnav .viewbtn { flex: 1; text-align: center; padding: 0.3rem 0.4rem; }

  .content { padding: 1rem; }
  .picks { grid-template-columns: 1fr; }
  .pick { flex-direction: column; gap: 0.25rem; }
  .pick > * { width: 100%; }
  .pick-text { padding-top: 0; }
  .shelf { grid-template-columns: 1fr; }
  .gigs { grid-template-columns: 1fr; }
}
</style>
