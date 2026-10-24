// The release record as the scrapers write it to /releases/<id>, and plain
// helpers to read it. Plain functions rather than a composable, there is no
// state to share: nuxt auto-imports everything exported from utils/, so these
// are usable in any template or script without an import

export interface StoreTags {
  preorder?: boolean
  out_of_stock?: boolean
  low_stock?: boolean
  has_charted?: boolean
  // sold out at some point. the scrapers disagree on the name: redeye and
  // yoyaku write has_been_out_of_stock, juno, hardwax and decks has_sold_out
  has_been_out_of_stock?: boolean
  has_sold_out?: boolean
}

export interface Video {
  uri: string
  title?: string
}

// firebase stores arrays with gaps as objects keyed by index, so list fields
// can arrive as either — read them through toArray
type List<T> = T[] | Record<string, T>

export interface Release {
  id: string
  artist?: string
  title?: string
  label?: string
  cat?: string
  link?: string
  store?: string
  artworks?: List<string>
  track_urls?: List<string>
  track_names?: List<string>
  videos?: Video[]       // discogs results only
  cover_image?: string   // discogs results only
  thumb?: string         // discogs results only
  store_tags?: StoreTags
  // per view rank keys ("<store>-<section>-<view>": position) and anything
  // else a scraper or the homepage adds
  [key: string]: any
}

export const FALLBACK_ART = '/white_label.jpg'

export function toArray<T>(val: List<T> | null | undefined): T[] {
  if (!val) return []
  return Array.isArray(val) ? val : Object.values(val)
}

// ── Artwork ──────────────────────────────────────────────────────────────────

// index into the artworks array to use as the tile image, per store
const STORE_ART_INDEX: Record<string, number> = {
  redeye:  0,
  juno:    0,
  phonica: 0,
  yoyaku:  1,
  hardwax: 1,
  decks:   1,
}

export function artworkUrl(release: Release): string | null {
  const urls = toArray(release.artworks)
  if (!urls.length) return null
  if (release.store === 'redeye') return urls.find(u => u.includes('-1.')) ?? urls[0] ?? null
  return urls[STORE_ART_INDEX[release.store ?? ''] ?? 0] ?? urls[0] ?? null
}

// ── Text ─────────────────────────────────────────────────────────────────────

// label / catalogue line above a release tile, matching the native app's
// "LABEL: CAT" format (see release_label_cat_more in app/code/main.cpp).
// stores vary in what they carry — phonica has no catalogue numbers at all,
// so fall back to whichever half exists rather than rendering nothing
export function labelCat(release: Release): string {
  const label = (release.label ?? '').trim()
  const cat   = (release.cat ?? '').trim()
  if (label && cat) return `${label}: ${cat}`
  return label || cat
}

// discogs titles come as "Artist - Title"
export function parseTitle(raw: string | undefined): { artist: string, title: string } {
  const s   = raw ?? ''
  const sep = s.indexOf(' - ')
  return sep === -1
    ? { artist: '', title: s }
    : { artist: s.slice(0, sep), title: s.slice(sep + 3) }
}

// ── Store state ──────────────────────────────────────────────────────────────

function tags(release: Release): StoreTags { return release?.store_tags || {} }

export function isPreorder(release: Release): boolean { return !!tags(release).preorder }
export function isSoldOut(release: Release): boolean  { return !!tags(release).out_of_stock }
export function isLowStock(release: Release): boolean { return !!tags(release).low_stock }
export function hasCharted(release: Release): boolean { return !!tags(release).has_charted }

// sold out at some point, now or before
export function hasBeenSoldOut(release: Release): boolean {
  const t = tags(release)
  return !!(t.has_been_out_of_stock || t.has_sold_out)
}

// sold out at some point and in stock again now
export function isBackInStock(release: Release): boolean {
  return hasBeenSoldOut(release) && !isSoldOut(release)
}

// ── Lists ────────────────────────────────────────────────────────────────────

// concatenate lists dropping repeats by id, keeping the first occurrence. a
// release can sit in several sections of a store
export function uniqueById(lists: Release[][]): Release[] {
  const seen = new Set<string>()
  const out: Release[] = []
  for (const list of lists) {
    for (const r of list) {
      if (!seen.has(r.id)) { seen.add(r.id); out.push(r) }
    }
  }
  return out
}

export function openLink(url: string | undefined) {
  if (url) window.open(url, '_blank', 'noopener')
}
