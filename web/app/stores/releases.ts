// stores/releases.js
import { defineStore } from 'pinia'
import { useDatabase } from 'vuefire'
import { ref as dbRef, query, orderByChild, equalTo, limitToFirst, startAfter, get } from 'firebase/database'

export const useReleasesStore = defineStore('releases', {
  state: () => ({
    releases: [],
    loading: false,
    hasMore: true,
    lastKey: null,
    selectedStore: 'all',
    selectedSection: 'all',
    selectedView: 'all',
    pageSize: 20,
    initialLoadSize: 50,
    isInitialized: false,
    storesData: null, // Will contain the stores.json structure
    lastFetched: null // Timestamp of last fetch
  }),

  getters: {
    // Get available stores from stores.json
    availableStores: (state) => {
      if (!state.storesData) return ['all']
      return ['all', ...Object.keys(state.storesData)].sort()
    },

    // Get sections for selected store
    availableSections: (state) => {
      if (!state.storesData || state.selectedStore === 'all') return ['all']
      const store = state.storesData[state.selectedStore]
      if (!store || !store.sections) return ['all']
      return ['all', ...Object.keys(store.sections)].sort()
    },

    // Get views for selected store-section
    availableViews: (state) => {
      if (!state.storesData || state.selectedStore === 'all' || state.selectedSection === 'all') {
        return ['all']
      }
      const store = state.storesData[state.selectedStore]
      if (!store || !store.sections || !store.sections[state.selectedSection]) return ['all']
      const section = store.sections[state.selectedSection]
      if (!section.views) return ['all']
      return ['all', ...Object.keys(section.views)].sort()
    },

    // Build the triplet for querying
    currentTriplet: (state) => {
      if (state.selectedStore === 'all') return null

      const parts = [state.selectedStore]
      if (state.selectedSection !== 'all') {
        parts.push(state.selectedSection)
        if (state.selectedView !== 'all') {
          parts.push(state.selectedView)
        }
      }
      return parts.join('-')
    },

    filteredReleases: (state) => {
      // When using triplet query, all loaded releases are already filtered
      return state.releases
    }
  },

  actions: {
    // Initialize and load data
    async initialize() {
      if (this.isInitialized) return

      // Check if cached data is still fresh (24 hours)
      const CACHE_DURATION = 1000 * 60 * 60 * 24 // 24 hours
      const isCacheValid = this.lastFetched &&
                          (Date.now() - this.lastFetched < CACHE_DURATION)

      // If cache is valid and we have stores data, skip fetching stores
      if (isCacheValid && this.storesData) {
        console.log('Using cached stores data from persistent state')
      } else {
        // Load stores.json
        await this.loadStores()
      }

      this.isInitialized = true
    },

    // Load stores.json to get the structure
    async loadStores() {
      try {
        const db = useDatabase()
        const snapshot = await get(dbRef(db, 'stores'))

        if (snapshot.exists()) {
          this.storesData = snapshot.val()
          this.lastFetched = Date.now()
          console.log('Loaded stores structure:', Object.keys(this.storesData))
        } else {
          console.error('No stores data found')
        }
      } catch (error) {
        console.error('Error loading stores:', error)
      }
    },

    // Load releases based on current filter
    async loadReleases() {
      if (this.loading) return
      this.loading = true

      // Reset pagination when filter changes
      this.releases = []
      this.lastKey = null
      this.hasMore = true

      try {
        const db = useDatabase()
        let releasesQuery

        if (this.selectedStore !== 'all') {
          // Query by store field
          releasesQuery = query(
            dbRef(db, 'releases'),
            orderByChild('store'),
            equalTo(this.selectedStore),
            limitToFirst(this.initialLoadSize)
          )
        } else {
          // Load all releases if no filter
          releasesQuery = query(
            dbRef(db, 'releases'),
            limitToFirst(this.initialLoadSize)
          )
        }

        const snapshot = await get(releasesQuery)

        const data = []
        snapshot.forEach((child) => {
          data.push({ id: child.key, ...child.val() })
        })

        // Client-side filtering for section and view
        let filteredData = data
        if (this.selectedSection !== 'all') {
          filteredData = filteredData.filter(r => r.section === this.selectedSection)
        }
        if (this.selectedView !== 'all') {
          filteredData = filteredData.filter(r => r.view === this.selectedView)
        }

        this.releases = filteredData
        if (data.length > 0) {
          this.lastKey = data[data.length - 1].id
        }

        this.hasMore = data.length >= this.initialLoadSize

        console.log('Loaded releases:', filteredData.length, 'for store:', this.selectedStore)
      } catch (error) {
        console.error('Error loading releases:', error)
      } finally {
        this.loading = false
      }
    },

    async loadMore() {
      if (this.loading || !this.hasMore || !this.lastKey) {
        return
      }

      this.loading = true

      try {
        const db = useDatabase()
        let releasesQuery

        if (this.selectedStore !== 'all') {
          // Query by store with pagination
          releasesQuery = query(
            dbRef(db, 'releases'),
            orderByChild('store'),
            equalTo(this.selectedStore),
            startAfter(this.lastKey),
            limitToFirst(this.pageSize)
          )
        } else {
          // Load all releases with pagination
          releasesQuery = query(
            dbRef(db, 'releases'),
            startAfter(this.lastKey),
            limitToFirst(this.pageSize)
          )
        }

        const snapshot = await get(releasesQuery)

        const data = []
        snapshot.forEach((child) => {
          data.push({ id: child.key, ...child.val() })
        })

        console.log('Loaded:', data.length, 'more releases')

        // Client-side filtering for section and view
        let filteredData = data
        if (this.selectedSection !== 'all') {
          filteredData = filteredData.filter(r => r.section === this.selectedSection)
        }
        if (this.selectedView !== 'all') {
          filteredData = filteredData.filter(r => r.view === this.selectedView)
        }

        if (data.length < this.pageSize) {
          this.hasMore = false
        }

        if (filteredData.length > 0) {
          this.releases = [...this.releases, ...filteredData]
          this.lastKey = data[data.length - 1].id
        } else if (data.length === 0) {
          this.hasMore = false
        }
      } catch (error) {
        console.error('Error loading more:', error)
      } finally {
        this.loading = false
      }
    },

    // Update selected store and reload
    async setStore(store) {
      this.selectedStore = store
      this.selectedSection = 'all'
      this.selectedView = 'all'
      await this.loadReleases()
    },

    // Update selected section and reload
    async setSection(section) {
      this.selectedSection = section
      this.selectedView = 'all'
      await this.loadReleases()
    },

    // Update selected view and reload
    async setView(view) {
      this.selectedView = view
      await this.loadReleases()
    },

    reset() {
      this.releases = []
      this.lastKey = null
      this.hasMore = true
      this.isInitialized = false
      this.lastFetched = null
      this.selectedStore = 'all'
      this.selectedSection = 'all'
      this.selectedView = 'all'
    }
  },

  persist: true
})