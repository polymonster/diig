// artIndex per store — index into the artworks array to use as the tile image
const STORE_ART_INDEX: Record<string, number> = {
  redeye:  0,
  juno:    0,
  phonica: 0,
  yoyaku:  1,
  hardwax: 1,
  decks:   1,
}

export function artworkUrl(release: any): string | null {
  const a = release.artworks
  if (!a) return null
  const urls: string[] = Array.isArray(a) ? a : Object.values(a)
  if (release.store === 'redeye') return urls.find(u => u.includes('-1.')) ?? urls[0] ?? null
  return urls[STORE_ART_INDEX[release.store] ?? 0] ?? urls[0] ?? null
}
