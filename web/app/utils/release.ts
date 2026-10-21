// Store state for a release, as the scrapers record it in store_tags. Plain
// functions rather than a composable, there is no state to share: auto-imported
// everywhere, templates and app.vue included

export function tags(release: any) { return release?.store_tags || {} }

export function isPreorder(release: any): boolean { return !!tags(release).preorder }
export function isSoldOut(release: any): boolean { return !!tags(release).out_of_stock }
export function isLowStock(release: any): boolean { return !!tags(release).low_stock }
export function hasCharted(release: any): boolean { return !!tags(release).has_charted }

// sold out at some point, now or before. the scrapers disagree on the name:
// redeye and yoyaku write has_been_out_of_stock, juno, hardwax and decks
// write has_sold_out
export function hasBeenSoldOut(release: any): boolean {
  const t = tags(release)
  return !!(t.has_been_out_of_stock || t.has_sold_out)
}

// sold out at some point and in stock again now
export function isBackInStock(release: any): boolean {
  return hasBeenSoldOut(release) && !isSoldOut(release)
}

export function openLink(url: string) {
  if (url) window.open(url, '_blank', 'noopener')
}
