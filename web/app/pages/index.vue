<script setup>
import { useCurrentUser } from 'vuefire'
import { useReleasesStore } from '@/stores/releases'
import { storeToRefs } from 'pinia'

const user = useCurrentUser()
const releasesStore = useReleasesStore()

// Use storeToRefs to keep reactivity
const {
  filteredReleases,
  availableStores,
  availableSections,
  availableViews,
  loading,
  hasMore,
  selectedStore,
  selectedSection,
  selectedView,
  releases
} = storeToRefs(releasesStore)

// Capitalize store name for display
function formatName(name) {
  if (name === 'all') return 'All'
  return name.charAt(0).toUpperCase() + name.slice(1)
}

// Load data when user logs in
watch(user, async (newUser) => {
  if (newUser) {
    await releasesStore.initialize()
    // Load initial releases
    if (releases.value.length === 0) {
      await releasesStore.loadReleases()
    }
  }
}, { immediate: true })

// Scroll handler for infinite scroll
function handleScroll() {
  const scrollPosition = window.innerHeight + window.scrollY
  const bottomPosition = document.documentElement.scrollHeight - 300

  if (scrollPosition >= bottomPosition && !loading.value && hasMore.value) {
    releasesStore.loadMore()
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

      <!-- Filter dropdowns -->
      <div class="space-y-3">
        <!-- Store filter -->
        <div class="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
          <label for="store-filter" class="text-sm font-medium text-gray-700 w-20">
            Store:
          </label>
          <select
            id="store-filter"
            :value="selectedStore"
            @change="releasesStore.setStore($event.target.value)"
            class="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
          >
            <option v-for="store in availableStores" :key="store" :value="store">
              {{ formatName(store) }}
            </option>
          </select>
        </div>

        <!-- Section filter (only show if store is selected) -->
        <div v-if="selectedStore !== 'all'" class="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
          <label for="section-filter" class="text-sm font-medium text-gray-700 w-20">
            Section:
          </label>
          <select
            id="section-filter"
            :value="selectedSection"
            @change="releasesStore.setSection($event.target.value)"
            class="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
          >
            <option v-for="section in availableSections" :key="section" :value="section">
              {{ formatName(section) }}
            </option>
          </select>
        </div>

        <!-- View filter (only show if section is selected) -->
        <div v-if="selectedStore !== 'all' && selectedSection !== 'all'" class="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
          <label for="view-filter" class="text-sm font-medium text-gray-700 w-20">
            View:
          </label>
          <select
            id="view-filter"
            :value="selectedView"
            @change="releasesStore.setView($event.target.value)"
            class="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
          >
            <option v-for="view in availableViews" :key="view" :value="view">
              {{ formatName(view) }}
            </option>
          </select>
        </div>

        <div class="text-sm text-gray-500">
          {{ filteredReleases.length }} releases
        </div>
      </div>
    </div>

    <!-- Releases list -->
    <div class="space-y-4">
      <div
        v-for="release in filteredReleases"
        :key="release.id"
        class="flex gap-4 items-start"
      >
        <!-- TODO: Backup image & check through images -->
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
          <!-- <pre>{{ release }}</pre> -->
          <!-- TODO: Check through tracks -->
          <audio controls :src="release.track_urls[0]"></audio>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="filteredReleases.length === 0 && !loading" class="text-center py-12">
      <p class="text-gray-500">No releases found</p>
    </div>

    <!-- Loading spinner -->
    <div v-if="loading" class="text-center py-8">
      <div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900"></div>
      <p class="mt-2 text-gray-600">Loading...</p>
    </div>

    <!-- Manual load button as backup -->
    <div v-if="hasMore && !loading && releases.length > 0" class="text-center py-8">
      <button
        @click="releasesStore.loadMore()"
        class="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
      >
        Load More
      </button>
    </div>

    <!-- End of list -->
    <div v-if="!hasMore && releases.length > 0" class="text-center py-8 text-gray-500">
      That's all! Loaded {{ releases.length }} releases
    </div>
  </div>

  <div v-else class="text-center py-20">
    <p class="text-xl">Please log in to view releases</p>
  </div>
</template>