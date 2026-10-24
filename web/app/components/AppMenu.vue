<script setup lang="ts">
import { useCurrentUser } from 'vuefire'

// the dropdown under the header's burger button
const user         = useCurrentUser()
const menuOpen     = useState('menuOpen', () => false)
const settingsOpen = useState('settingsOpen', () => false)
const showDebug    = useState('showDebug', () => storageGet('showDebug') === 'true')
const { displayName } = useProfile()

watch(showDebug, val => storageSet('showDebug', String(val)))

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
      <label class="item toggle">
        <span>Show Debug</span>
        <input v-model="showDebug" type="checkbox">
      </label>
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

.toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  border-bottom: 1px solid #f0f0f0;
}
</style>
