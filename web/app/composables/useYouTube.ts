// Module-level singletons — one player per browser tab, persists across navigation
const ytActiveId    = ref<string | null>(null)
const ytActiveTrack = ref<number>(0)
const ytPlaying     = ref<boolean>(false)
const ytOpen        = ref<boolean>(false)
const ytReleaseList = ref<any[]>([])  // [{id, title, thumb, cover_image, videos:[{uri,title}]}]

let ytPlayer: any   = null
let ytPending: string | null = null

function extractVideoId(url: string | undefined): string | null {
  if (!url) return null
  const m = url.match(/[?&]v=([^&#]+)/) || url.match(/youtu\.be\/([^?&#]+)/)
  return m?.[1] ?? null
}

async function ensurePlayer(): Promise<void> {
  if (ytPlayer) return
  await new Promise<void>(resolve => {
    if ((window as any).YT?.Player) { resolve(); return }
    ;(window as any).onYouTubeIframeAPIReady = resolve
    if (!document.querySelector('script[src*="youtube.com/iframe_api"]')) {
      const s = document.createElement('script')
      s.src = 'https://www.youtube.com/iframe_api'
      document.head.appendChild(s)
    }
  })
  ytPlayer = new (window as any).YT.Player('yt-iframe', {
    height: '68', width: '120', videoId: '',
    playerVars: { autoplay: 1, controls: 0, rel: 0, modestbranding: 1, iv_load_policy: 3, playsinline: 1 },
    events: {
      onReady(e: any)       { if (ytPending) e.target.loadVideoById(ytPending) },
      onStateChange(e: any) {
        ytPlaying.value = e.data === 1
        if (e.data === 0) autoNext()
      },
    },
  })
}

function getVideos(release: any): any[] { return release?.videos ?? [] }

function activeRelease(): any {
  return ytReleaseList.value.find(r => String(r.id) === ytActiveId.value) ?? null
}

async function setTrack(release: any, idx: number): Promise<void> {
  const vid = extractVideoId(getVideos(release)[idx]?.uri)
  if (!vid) return
  ytActiveId.value    = String(release.id)
  ytActiveTrack.value = idx
  ytOpen.value        = true
  ytPending           = vid
  if (!ytPlayer) {
    await nextTick()  // ensure #yt-iframe is in the DOM before creating the player
    await ensurePlayer()
  } else {
    ytPlayer.loadVideoById(vid)
  }
}

function autoNext(): void {
  const rel  = activeRelease()
  const vids = getVideos(rel)
  if (rel && ytActiveTrack.value + 1 < vids.length) { setTrack(rel, ytActiveTrack.value + 1); return }
  const ci = ytReleaseList.value.findIndex(r => String(r.id) === ytActiveId.value)
  for (let i = ci + 1; i < ytReleaseList.value.length; i++) {
    if (getVideos(ytReleaseList.value[i]).length) { setTrack(ytReleaseList.value[i], 0); return }
  }
  ytPlaying.value = false
}

export function useYouTube() {
  function tileClick(release: any) {
    if (String(release.id) === ytActiveId.value) toggle()
    else if (getVideos(release).length) setTrack(release, 0)
  }

  function dotClick(release: any, idx: number, e: Event) {
    e.stopPropagation()
    setTrack(release, idx)
  }

  function prevTrack(e?: Event) {
    e?.stopPropagation()
    const rel = activeRelease()
    if (!rel) return
    if (ytActiveTrack.value > 0) { setTrack(rel, ytActiveTrack.value - 1); return }
    const ci = ytReleaseList.value.findIndex(r => String(r.id) === ytActiveId.value)
    for (let i = ci - 1; i >= 0; i--) {
      const vids = getVideos(ytReleaseList.value[i])
      if (vids.length) { setTrack(ytReleaseList.value[i], vids.length - 1); return }
    }
  }

  function nextTrack(e?: Event) {
    e?.stopPropagation()
    const rel  = activeRelease()
    const vids = getVideos(rel)
    if (rel && ytActiveTrack.value < vids.length - 1) { setTrack(rel, ytActiveTrack.value + 1); return }
    const ci = ytReleaseList.value.findIndex(r => String(r.id) === ytActiveId.value)
    for (let i = ci + 1; i < ytReleaseList.value.length; i++) {
      if (getVideos(ytReleaseList.value[i]).length) { setTrack(ytReleaseList.value[i], 0); return }
    }
  }

  function toggle() {
    if (!ytPlayer) return
    ytPlaying.value ? ytPlayer.pauseVideo() : ytPlayer.playVideo()
  }

  function close() { ytPlayer?.pauseVideo(); ytOpen.value = false }

  function stopAll() {
    ytPlayer?.stopVideo()
    ytPlayer?.destroy()
    ytPlayer  = null
    ytPending = null
    ytOpen.value = false; ytActiveId.value = null; ytActiveTrack.value = 0; ytPlaying.value = false
    ytReleaseList.value = []
  }

  const canPrev = computed(() => {
    const rel = activeRelease()
    if (!rel) return false
    if (ytActiveTrack.value > 0) return true
    const ci = ytReleaseList.value.findIndex(r => String(r.id) === ytActiveId.value)
    return ytReleaseList.value.slice(0, ci).some(r => getVideos(r).length > 0)
  })

  const canNext = computed(() => {
    const rel  = activeRelease()
    const vids = getVideos(rel)
    if (ytActiveTrack.value < vids.length - 1) return true
    const ci = ytReleaseList.value.findIndex(r => String(r.id) === ytActiveId.value)
    return ytReleaseList.value.slice(ci + 1).some(r => getVideos(r).length > 0)
  })

  return {
    ytActiveId, ytActiveTrack, ytPlaying, ytOpen, ytReleaseList,
    getVideos, setTrack, tileClick, dotClick, prevTrack, nextTrack,
    toggle, close, stopAll, canPrev, canNext,
  }
}
