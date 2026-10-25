import type { Release } from '~/utils/release'

// The weekly curated homepage, written to /homepage/current by scrape/homepage.py

export interface HomepageRelease extends Release {
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

export interface Homepage {
  week: string
  headline: string
  intro: string
  picks?: HomepageRelease[]
  hype?: HomepageRelease[]
  gigs?: Gig[]
}

const page    = ref<Homepage | null>(null)
const loading = ref(false)

export function useHomepage() {
  const db = useDb()

  async function loadHomepage() {
    loading.value = true
    page.value    = await db.get<Homepage>('homepage/current')
    loading.value = false
  }

  return { page, loading, loadHomepage }
}
