<script setup lang="ts">
import { useCurrentUser } from 'vuefire'

// the dropdown under the header's burger button
const user         = useCurrentUser()
const menuOpen     = useState('menuOpen', () => false)
const settingsOpen = useState('settingsOpen', () => false)
const { displayName } = useProfile()
const { testflightUrl, androidUrl } = useRuntimeConfig().public

function openSettings() {
  settingsOpen.value = true
  menuOpen.value     = false
}
</script>

<template>
  <template v-if="menuOpen">
    <div class="backdrop" @click="menuOpen = false" />
    <div class="menu">
      <div v-if="user" class="username">{{ displayName }}</div>
      <a v-if="testflightUrl" :href="testflightUrl" target="_blank" rel="noopener" class="item link" @click="menuOpen = false">Get the iOS app</a>
      <a v-if="androidUrl" :href="androidUrl" target="_blank" rel="noopener" class="item link" @click="menuOpen = false">Get the Android app</a>
      <button class="item" @click="openSettings">Settings</button>
    </div>
  </template>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 150;
}

.menu {
  position: fixed;
  top: 3.4rem;
  right: 0.75rem;
  z-index: 160;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 4px;
  min-width: 180px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.username {
  padding: 0.55rem 0.9rem;
  font-size: 0.6rem;
  color: #aaa;
  border-bottom: 1px solid #f0f0f0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item {
  background: none;
  border: none;
  padding: 0.45rem 0.9rem;
  font-size: 0.65rem;
  text-align: left;
  cursor: pointer;
  color: #333;
}
.item:hover { background: #f9f9f9; }

.link {
  text-decoration: none;
  border-bottom: 1px solid #f0f0f0;
}
</style>
