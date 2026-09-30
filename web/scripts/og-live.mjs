// Post-generate: give /live its own link-preview card.
//
// Why a script rather than useHead(): the site is `ssr: false`, so Nuxt emits
// a JS-only shell with no per-route head. Social scrapers don't execute JS, so
// anything set from Vue is invisible to them. The tags have to be in the HTML
// on disk, which means patching the generated file.
//
// The card image is a frame from the latest recording, whose UID lives in RTDB
// (`/live/lastRecording`, world-readable). Reading it at build time means the
// preview refreshes on each deploy instead of pinning one mix forever.

import { readFile, writeFile } from 'node:fs/promises'

const OUT  = new URL('../.output/public/live/index.html', import.meta.url)
const DB   = 'https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app'
const SITE = 'https://diig.app'
const CODE = process.env.NUXT_PUBLIC_CF_CUSTOMER_CODE || ''

const warn = msg => console.warn(`[og-live] ${msg} — falling back to site defaults`)

async function lastRecording() {
  if (!CODE) { warn('NUXT_PUBLIC_CF_CUSTOMER_CODE unset'); return null }
  try {
    const res = await fetch(`${DB}/live.json`, { signal: AbortSignal.timeout(10_000) })
    if (!res.ok) { warn(`RTDB /live returned ${res.status}`); return null }
    const meta = await res.json()
    return meta?.lastRecording ?? null
  } catch (err) {
    warn(`RTDB /live unreachable (${err.message})`)
    return null
  }
}

const esc = s => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')

const uid   = await lastRecording()
const image = uid
  ? `https://customer-${CODE}.cloudflarestream.com/${uid}/thumbnails/thumbnail.jpg?width=1200&height=630&fit=crop`
  : `${SITE}/icon.png`

const title = 'diig — live'
const desc  = 'live mixes'

const tags = [
  `<title>${esc(title)}</title>`,
  `<meta name="description" content="${esc(desc)}">`,
  `<meta property="og:site_name" content="diig">`,
  `<meta property="og:type" content="video.other">`,
  `<meta property="og:title" content="${esc(title)}">`,
  `<meta property="og:description" content="${esc(desc)}">`,
  `<meta property="og:url" content="${SITE}/live">`,
  `<meta property="og:image" content="${esc(image)}">`,
  `<meta property="og:image:width" content="1200">`,
  `<meta property="og:image:height" content="630">`,
  `<meta name="twitter:card" content="summary_large_image">`,
].join('')

let html
try {
  html = await readFile(OUT, 'utf8')
} catch {
  console.warn('[og-live] .output/public/live/index.html missing — did generate run? skipping')
  process.exit(0)
}

// Drop the site-wide defaults for this page, then insert the /live versions.
const stripped = html.replace(
  /<title>.*?<\/title>|<meta (?:name="(?:description|twitter:card)"|property="og:[^"]*")[^>]*>/g,
  '',
)

if (!stripped.includes('</head>')) {
  console.warn('[og-live] no </head> in generated shell — skipping')
  process.exit(0)
}

await writeFile(OUT, stripped.replace('</head>', `${tags}</head>`))
console.log(`[og-live] /live card set, image: ${uid ? 'recording thumbnail' : 'icon.png fallback'}`)
