<script setup lang="ts">
import { useCurrentUser } from 'vuefire'
import type { Release } from '~/utils/release'

// Everything the user has liked, most recent first

const user = useCurrentUser()
const db   = useDb()
const { likes, isLiked, loadLikes } = useLikes()
const { stores, loadStores } = useStores()
const { releaseList } = usePlayer()

const releases = ref<Release[]>([])
const loading  = ref(false)

async function loadLikedReleases() {
  loading.value = true
  // likes are already loading from app.vue on sign in, this shares that request
  await Promise.all([loadLikes(), stores.value.length ? null : loadStores()])

  // timestamp order, skipping 0 un-like tombstones
  const ids = Object.entries(likes.value)
    .filter(([, ts]) => ts > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([id]) => id)

  const found = await Promise.all(ids.map(id => db.get<Release>(`releases/${id}`)))
  releases.value = found.flatMap((r, i) => r ? [{ ...r, id: ids[i]! }] : [])
  loading.value  = false
}

watch(user, u => { if (u) loadLikedReleases() }, { immediate: true })

// an un-like on this page takes the release off it
const shown = computed(() => releases.value.filter(r => isLiked(r.id)))

watch(shown, val => { releaseList.value = val })

function storeName(release: Release) {
  return stores.value.find(s => s.id === release.store)?.name ?? release.store ?? ''
}
</script>

<template>
  <div class="page">
    <AppHeader>
      <span class="page-title">likes</span>
    </AppHeader>

    <LoadingSpinner v-if="loading" full />

    <main v-else class="content">
      <p v-if="!shown.length" class="empty">no liked releases yet</p>
      <div v-else class="shelf">
        <ReleaseTile v-for="release in shown" :key="release.id" :release="release" :sub="storeName(release)" />
      </div>
    </main>
  </div>
</template>
