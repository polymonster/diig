// label / catalogue line above a release tile, matching the native app's
// "LABEL: CAT" format (see release_label_cat_more in app/code/main.cpp).
// stores vary in what they carry — phonica has no catalogue numbers at all,
// so fall back to whichever half exists rather than rendering nothing
export function labelCat(release: any): string {
  const label = (release.label ?? '').trim()
  const cat   = (release.cat ?? '').trim()
  if (label && cat) return `${label}: ${cat}`
  return label || cat
}
