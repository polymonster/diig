<script setup lang="ts">
// The sticky bar at the top of every signed in page: logo, whatever the page
// puts in the slot (nav tabs, selects, a search box), then the live badge,
// likes and the menu on the right.
//
// For the slot, main.css has .viewnav / .viewbtn (tabs that wrap onto their
// own row on mobile) and .page-title (a plain label)

const route    = useRoute()
const menuOpen = useState('menuOpen', () => false)
const { isLive } = useLiveStatus()
</script>

<template>
  <header class="header">
    <NuxtLink to="/" class="logo">diig</NuxtLink>
    <slot />
    <div class="header-right">
      <NuxtLink v-if="isLive && route.path !== '/live'" to="/live" class="live-nav">
        <span class="live-dot" />live
      </NuxtLink>
      <NuxtLink to="/likes" class="likes-nav">
        <span class="fa">{{ ICON.heart }}</span>
      </NuxtLink>
      <button class="burger-btn fa" @click="menuOpen = !menuOpen">{{ ICON.bars }}</button>
    </div>
  </header>
</template>

<style scoped>
.header {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  padding: 1rem 1.5rem;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
  position: sticky;
  top: 0;
  z-index: 10;
}

.logo {
  font-size: 1.1rem;
  letter-spacing: 0.1em;
  color: var(--ink);
  text-decoration: none;
  white-space: nowrap;
}

.header-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.9rem;
  flex-shrink: 0;
}

.live-nav {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.6rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  text-decoration: none;
  color: var(--accent);
}

.likes-nav {
  font-size: 1rem;
  color: #ccc;
  text-decoration: none;
  transition: color 0.15s;
}
.likes-nav:hover,
.likes-nav.router-link-active { color: var(--like); }

.burger-btn {
  background: none;
  border: none;
  font-size: 1rem;
  cursor: pointer;
  color: #bbb;
  padding: 0;
  line-height: 1;
}
.burger-btn:hover { color: #555; }

/* mobile: logo and icons on the first row, the slot content wraps below */
@media (max-width: 600px) {
  .header {
    flex-wrap: wrap;
    gap: 0.6rem;
    padding: 0.75rem 1rem;
  }
}
</style>
