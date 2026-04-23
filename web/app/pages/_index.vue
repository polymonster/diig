<script setup>
import { ref as vueRef, watch, computed } from 'vue'
import { useDatabase, useCurrentUser } from 'vuefire'
import { ref as dbRef, query, orderByKey, limitToFirst, startAfter, get } from 'firebase/database'

const db = useDatabase()
const user = useCurrentUser()

const releases = vueRef([])
const loading = vueRef(false)
const hasMore = vueRef(true)
const lastKey = vueRef(null)
const pageSize = 20
const initialLoadSize = 30 // Load more initially to populate filters
const selectedStore = vueRef('all')

// Get unique stores from the "store" field in release data
const availableStores = computed(() => {
  const storesSet = new Set()

  releases.value.forEach(release => {
    if (release.store) {
      storesSet.add(release.store)
    }
  })

  return ['all', ...Array.from(storesSet)].sort()
})

// Filter releases by selected store
const filteredReleases = computed(() => {
  if (selectedStore.value === 'all') {
    return releases.value
  }

  return releases.value.filter(release => release.store === selectedStore.value)
})

// Capitalize store name for display
function formatStoreName(store) {
  if (store === 'all') return 'All Stores'
  return store.charAt(0).toUpperCase() + store.slice(1)
}

// Load initial batch when user logs in
watch(user, async (newUser) => {
  if (newUser && releases.value.length === 0) {
    await loadInitial()
  }
}, { immediate: true })

async function loadInitial() {
  if (loading.value) return
  loading.value = true

  try {
    const snapshot = await get(
      query(
        dbRef(db, 'releases'),
        orderByKey(),
        limitToFirst(initialLoadSize) // Start from the beginning (alphabetically)
      )
    )

    const data = []
    snapshot.forEach((child) => {
      data.push({ id: child.key, ...child.val() })
    })

    releases.value = data
    if (data.length > 0) {
      lastKey.value = data[data.length - 1].id
    }

    if (data.length < initialLoadSize) {
      hasMore.value = false
    }

    console.log('Initial load:', data.length, 'releases')
    console.log('First ID:', data[0]?.id, 'Last ID:', data[data.length - 1]?.id)
  } catch (error) {
    console.error('Error loading releases:', error)
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  if (loading.value || !hasMore.value || !lastKey.value) {
    return
  }

  loading.value = true

  try {
    const snapshot = await get(
      query(
        dbRef(db, 'releases'),
        orderByKey(),
        startAfter(lastKey.value), // Get items after the last key
        limitToFirst(pageSize)
      )
    )

    const data = []
    snapshot.forEach((child) => {
      data.push({ id: child.key, ...child.val() })
    })

    console.log('Loaded:', data.length, 'more releases')

    if (data.length < pageSize) {
      hasMore.value = false
    }

    if (data.length > 0) {
      releases.value = [...releases.value, ...data]
      lastKey.value = data[data.length - 1].id
    } else {
      hasMore.value = false
    }
  } catch (error) {
    console.error('Error loading more:', error)
  } finally {
    loading.value = false
  }
}

// Simple scroll handler
function handleScroll() {
  const scrollPosition = window.innerHeight + window.scrollY
  const bottomPosition = document.documentElement.scrollHeight - 300

  if (scrollPosition >= bottomPosition && !loading.value && hasMore.value) {
    loadMore()
  }
}

onMounted(() => {
  window.addEventListener('scroll', handleScroll)
})

onUnmounted(() => {
  window.removeEventListener('scroll', handleScroll)
})
</script>

<template>
  <div v-if="user" class="max-w-4xl mx-auto p-6">
    <div class="mb-6">
      <h1 class="text-3xl font-bold mb-4">Releases</h1>

      <!-- Store filter dropdown -->
      <div class="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
        <label for="store-filter" class="text-sm font-medium text-gray-700">
          Filter by Store:
        </label>
        <select
          id="store-filter"
          v-model="selectedStore"
          class="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
        >
          <option v-for="store in availableStores" :key="store" :value="store">
            {{ formatStoreName(store) }}
          </option>
        </select>

        <span class="text-sm text-gray-500">
          ({{ filteredReleases.length }} releases)
        </span>
      </div>
    </div>

    <!-- Releases list -->
    <div class="space-y-4">
      <div
        v-for="release in filteredReleases"
        :key="release.id"
        class="flex gap-4 items-start"
      >
        <img
          v-if="release.artworks && release.artworks[0]"
          :src="release.artworks[0]"
          :alt="release.title"
          class="w-16 h-16 sm:w-24 sm:h-24 md:w-32 md:h-32 object-cover rounded flex-shrink-0"
        />

        <div class="flex-1 min-w-0">
          <p class="text-lg text-gray-900 font-medium truncate">
            {{ release.artist || 'Unknown Artist' }}
          </p>
          <p class="text-sm text-gray-600 truncate">{{ release.title }}</p>
          <p class="text-xs text-gray-400">{{ release.label }}</p>
          <p class="text-xs text-gray-400">{{ release.store }} • {{ release.id }}</p>
        </div>
      </div>
    </div>

    <!-- Empty state when filtered -->
    <div v-if="filteredReleases.length === 0 && releases.length > 0" class="text-center py-12">
      <p class="text-gray-500">No releases found for this store</p>
    </div>

    <!-- Loading spinner -->
    <div v-if="loading" class="text-center py-8">
      <div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900"></div>
      <p class="mt-2 text-gray-600">Loading more...</p>
    </div>

    <!-- Manual load button as backup -->
    <div v-if="hasMore && !loading" class="text-center py-8">
      <button
        @click="loadMore"
        class="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
      >
        Load More
      </button>
    </div>

    <!-- End of list -->
    <div v-if="!hasMore" class="text-center py-8 text-gray-500">
      That's all! Loaded {{ releases.length }} releases
    </div>
  </div>

  <div v-else class="text-center py-20">
    <p class="text-xl">Please log in to view releases</p>
  </div>
</template>