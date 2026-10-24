import type { Release } from '~/utils/release'

// The store catalogue (/stores, written by the scrapers) and the ranked
// release lists behind each store / section / view.
//
// Releases are indexed by "rank keys": a release in juno's house section
// new releases list carries `"juno-house-new_releases": 3`. Fetching a list is
// an orderBy query on that key.

export interface StoreView {
  id: string
  label: string
  sectionless: boolean   // the view is one list for the whole store, not per section
}

export interface StoreSection {
  id: string
  name: string
}

export interface Store {
  id: string
  name: string
  views: StoreView[]       // in display order
  sections: StoreSection[]
  chartView: string        // the view the home page "Hot" tab shows for this store
}

const DEFAULT_VIEW_ORDER = ['new_releases', 'weekly_chart', 'monthly_chart']

function parseStore(id: string, d: any): Store {
  const views = d.views || {}
  const order: string[] = d.view_order || DEFAULT_VIEW_ORDER
  const ids = [
    ...order.filter(v => views[v]),
    ...Object.keys(views).filter(v => !order.includes(v)),
  ]
  return {
    id,
    name: d.display_name || id.charAt(0).toUpperCase() + id.slice(1),
    views: ids.map(v => ({
      id:          v,
      label:       views[v].display_name || v,
      sectionless: !!views[v].sectionless,
    })),
    sections: (d.sections || []).map((secId: string, i: number) => ({
      id:   secId,
      name: (d.section_display_names || [])[i] || secId,
    })),
    chartView: (d.view_order || [])[1] || 'weekly_chart',
  }
}

// one copy for the whole app, so moving between pages doesn't refetch
const stores = ref<Store[]>([])

export function useStores() {
  const db = useDb()

  async function loadStores(): Promise<Store[]> {
    const data = await db.get('stores')
    if (data && typeof data === 'object') {
      stores.value = Object.entries(data).map(([id, d]) => parseStore(id, d))
    }
    return stores.value
  }

  // the ids of the sections to fetch for a view: one pseudo section for a
  // sectionless view, otherwise every section
  function sectionIds(store: Store, viewId: string): string[] {
    const view = store.views.find(v => v.id === viewId)
    return view?.sectionless ? ['sectionless'] : store.sections.map(s => s.id)
  }

  // the top `limit` releases of one section in one view, in rank order
  async function loadReleases(storeId: string, sectionId: string, viewId: string, limit: number): Promise<Release[]> {
    const key  = `${storeId}-${sectionId}-${viewId}`
    const data = await db.get<Record<string, any>>('releases', { orderBy: `"${key}"`, startAt: '0' })
    if (!data || typeof data !== 'object') return []
    // spread first so the firebase key wins; release records carry their own
    // store-local 'id' field which would otherwise shadow it
    const items: Release[] = Object.entries(data).map(([id, v]) => ({ ...v, id }))
    items.sort((a, b) => (a[key] ?? 999) - (b[key] ?? 999))
    return items.slice(0, limit)
  }

  return { stores, loadStores, sectionIds, loadReleases }
}
