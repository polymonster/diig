<script setup lang="ts">
import { useCurrentUser } from 'vuefire'

// The shell around every page: the overlays that live across page changes.
// Global styles are in assets/css/main.css

const user = useCurrentUser()
const { loadLikes }   = useLikes()
const { loadProfile } = useProfile()

// per user data shared by the pages, (re)loaded on sign in / out
watch(user, () => {
  loadLikes()
  loadProfile()
}, { immediate: true })
</script>

<template>
  <div>
    <NuxtPage />
    <AppMenu />
    <SettingsPanel />
    <PlayerBar />
    <DebugOverlay />
  </div>
</template>
