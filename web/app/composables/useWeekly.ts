import type { Release } from '~/utils/release'

// The weekly curated page, written to /weekly/current by scrape/weekly.py

export interface WeeklyRelease extends Release {
  blurb?: string
  // the review a pick's blurb is drawn from
  source?: { url: string, title: string, site: string }
  stores?: { store: string, link: string, out_of_stock?: boolean }[]
}

export interface Gig {
  id: string
  date: string    // yyyy-mm-dd
  venue: string
  title: string
  url: string
  flyer?: string
  blurb?: string
}

export interface Weekly {
  week: string
  headline: string
  intro: string
  picks?: WeeklyRelease[]
  hype?: WeeklyRelease[]
  gigs?: Gig[]
}

const page    = ref<Weekly | null>(null)
const loading = ref(false)

export function useWeekly() {
  const db = useDb()

  async function loadWeekly() {
    loading.value = true
    page.value    = await db.get<Weekly>('weekly/current')
    loading.value = false
  }

  return { page, loading, loadWeekly }
}
