// Live-stream status, shared across every page (the nav badge and /live both
// read it) — module-level singletons, one poller per tab.
//
// Cloudflare's live-input status API needs a bearer token we can't ship in a
// static SPA, so liveness is inferred from the HLS manifest instead: it 404s
// while nothing is ingesting and 200s once OBS connects. Stream serves
// manifests with permissive CORS, so a plain fetch works from the browser.

export interface LiveMeta {
  title?: string
  artist?: string
  next?: string   // free text, e.g. "saturday 21:00 CET"
}

const DB = 'https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app'

const isLive   = ref(false)
const checking = ref(true)
const meta     = ref<LiveMeta | null>(null)

// Poll cadence is the fastest any mounted consumer asked for: the nav badge is
// happy at a minute, /live wants ~10s so the flip feels immediate.
const intervals = new Map<number, number>()
let nextKey = 1
let timer: ReturnType<typeof setInterval> | null = null
let visibilityBound = false
let inFlight = false

let uid  = ''
let code = ''

// Both values are required. The generic hosts (videodelivery.net,
// iframe.cloudflarestream.com) are not a usable fallback: the manifest 404s
// there even while the input is live, and the embed loads but reports "video
// not found" because it can't resolve the account. Only the account subdomain
// serves this stream.
//
// Note the UID is the half of the RTMPS stream key *after* the `k`.

function host(): string {
  return `customer-${code}.cloudflarestream.com`
}

function manifestUrl(): string {
  if (!uid || !code) return ''
  return `https://${host()}/${uid}/manifest/video.m3u8`
}

function iframeUrl(): string {
  if (!uid || !code) return ''
  // primaryColor is the site accent; autoplay is best-effort (mobile blocks it
  // with sound, which just leaves the player's own tap-to-play).
  return `https://${host()}/${uid}/iframe?autoplay=true&primaryColor=%23cc4d00`
}

async function probe(): Promise<void> {
  const url = manifestUrl()
  if (!url) { isLive.value = false; checking.value = false; return }
  if (inFlight) return
  inFlight = true
  try {
    const res = await fetch(url, { cache: 'no-store' })
    isLive.value = res.ok
  } catch {
    // offline, blocked, or DNS — treat as not live rather than erroring the page
    isLive.value = false
  } finally {
    inFlight = false
    checking.value = false
  }
}

// Public read — logged-out viewers have no id token, so no ?auth= here.
// Requires `/live` to be world-readable in the RTDB rules.
async function loadMeta(): Promise<void> {
  try {
    const res = await fetch(`${DB}/live.json`, { cache: 'no-store' })
    if (!res.ok) return
    const data = await res.json()
    if (data && typeof data === 'object') meta.value = data as LiveMeta
  } catch {
    // metadata is decoration; the stream still plays without it
  }
}

function reschedule(): void {
  if (timer) { clearInterval(timer); timer = null }
  if (!intervals.size) return
  const ms = Math.min(...intervals.values())
  timer = setInterval(() => {
    if (!document.hidden) probe()
  }, ms)
}

function onVisibility(): void {
  // catch up immediately on return rather than waiting out the interval
  if (!document.hidden) probe()
}

export function useLiveStatus(pollMs = 60_000) {
  const rc = useRuntimeConfig().public
  uid  = String(rc.cfStreamUid || '')
  code = String(rc.cfCustomerCode || '')

  const key = nextKey++

  onMounted(() => {
    intervals.set(key, pollMs)
    reschedule()
    if (!visibilityBound) {
      document.addEventListener('visibilitychange', onVisibility)
      visibilityBound = true
    }
    probe()
    loadMeta()
  })

  onUnmounted(() => {
    intervals.delete(key)
    reschedule()
  })

  return {
    isLive,
    checking,
    meta,
    configured: computed(() => Boolean(uid && code)),
    iframeUrl:  computed(iframeUrl),
    probe,
    refreshMeta: loadMeta,
  }
}
