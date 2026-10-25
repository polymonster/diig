<script setup lang="ts">
import { useCurrentUser } from 'vuefire'

// The weekly curated page: picks with a blurb, hype releases and gigs

const user = useCurrentUser()
const { page, loading, loadHomepage } = useHomepage()
const { releaseList, stopAll } = usePlayer()

watch(user, u => { if (u) loadHomepage() }, { immediate: true })

const picks = computed(() => toArray(page.value?.picks))
const hype  = computed(() => toArray(page.value?.hype))
const gigs  = computed(() => toArray(page.value?.gigs))

watch([picks, hype], ([p, h]) => { releaseList.value = [...p, ...h] }, { immediate: true })
onUnmounted(stopAll)
</script>

<template>
  <div class="page">
    <AppHeader>
      <nav class="viewnav">
        <NuxtLink to="/" class="viewbtn">&lsaquo; Shelves</NuxtLink>
        <span class="viewbtn active">Weekly</span>
      </nav>
    </AppHeader>

    <LoadingSpinner v-if="loading && !page" full />

    <main v-else-if="page" class="content">
      <section class="intro">
        <p class="week">{{ page.week }}</p>
        <h1 class="headline">{{ page.headline }}</h1>
        <p class="intro-text">{{ page.intro }}</p>
      </section>

      <section v-if="picks.length" class="section">
        <h2 class="shelf-name">Picks</h2>
        <div class="picks">
          <div v-for="release in picks" :key="release.id" class="pick">
            <ReleaseTile :release="release" />
            <div class="pick-text">
              <p v-if="release.blurb" class="blurb">{{ release.blurb }}</p>
              <p v-if="release.blurb && release.source" class="source">
                via <a :href="release.source.url" :title="release.source.title" target="_blank">{{ release.source.site }}</a>
              </p>
              <p class="shops">{{ toArray(release.stores).map(s => s.store).join(' · ') }}</p>
            </div>
          </div>
        </div>
      </section>

      <section v-if="hype.length" class="section shelf">
        <h2 class="shelf-name">Hype</h2>
        <ReleaseTile v-for="release in hype" :key="release.id" :release="release">
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
      </section>

      <section v-if="gigs.length" class="section">
        <h2 class="shelf-name">London gigs</h2>
        <div class="gigs">
          <a v-for="gig in gigs" :key="gig.id" :href="gig.url" target="_blank" class="gig">
            <img v-if="gig.flyer" :src="gig.flyer" :alt="gig.title" class="gig-flyer" loading="lazy">
            <div class="gig-text">
              <p class="gig-date">{{ formatDay(gig.date) }} · {{ gig.venue }}</p>
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
.intro {
  max-width: 640px;
  margin: 0 auto 2rem;
}

.week {
  font-size: 0.6rem;
  letter-spacing: 0.15em;
  color: #bbb;
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
}

.section { margin-bottom: 2.5rem; }

/* ── Picks: tile with the blurb beside it ── */

.picks {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 1.25rem 2rem;
  margin-top: 0.5rem;
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

.source {
  font-size: 0.6rem;
  color: #999;
  margin: 0 0 0.4rem;
}

.source a {
  color: inherit;
}

.shops {
  font-size: 0.55rem;
  letter-spacing: 0.05em;
  color: #aaa;
}

/* ── Hype: store links under each tile ── */

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
.shop-link:hover { color: var(--ink); }
.shop-link.sold  { text-decoration: line-through; color: #ccc; }

/* ── Gigs ── */

.gigs {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1rem;
  margin-top: 0.5rem;
}

.gig {
  display: flex;
  gap: 0.75rem;
  color: inherit;
  text-decoration: none;
  background: var(--panel);
  border: 1px solid #e8e8e8;
  padding: 0.6rem;
  transition: border-color 0.15s;
}
.gig:hover { border-color: var(--ink); }

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
  color: var(--accent);
  margin-bottom: 2px;
}

.gig-title {
  font-size: 0.65rem;
  margin-bottom: 0.3rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 600px) {
  .picks      { grid-template-columns: 1fr; }
  .pick       { flex-direction: column; gap: 0.25rem; }
  .pick > *   { width: 100%; }
  .pick-text  { padding-top: 0; }
  .gigs       { grid-template-columns: 1fr; }
}
</style>
