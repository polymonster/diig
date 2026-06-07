// Module-level singletons — one player per browser tab (safe with ssr: false)

const activeId      = ref<string | null>(null)
const activeTrack   = ref<number>(0)
const isPlaying     = ref<boolean>(false)
const mode          = ref<'audio' | 'video' | null>(null)
const releaseList   = ref<any[]>([])
const activeRelease = ref<any | null>(null)

// Audio progress / volume
const currentTime = ref(0)
const duration    = ref(0)
const volume      = ref(1)

// YouTube-specific
const ytOpen = ref(false)
let ytPlayer: any       = null
let ytPending: string | null = null

// Audio-specific
let audioEl: HTMLAudioElement | null = null

export function usePlayer() {

  // ── Item accessors ──────────────────────────────────────────────────────────

  function toArray(val: any): any[] {
    if (!val) return []
    return Array.isArray(val) ? val : Object.values(val)
  }

  function getTracks(release: any): any[]     { return toArray(release?.track_urls) }
  function getTrackNames(release: any): any[] { return toArray(release?.track_names) }
  function getVideos(release: any): any[]     { return release?.videos ?? [] }

  function getItems(release: any): any[] {
    if (mode.value === 'audio') return getTracks(release)
    if (mode.value === 'video') return getVideos(release)
    return []
  }

  // ── Audio backend ───────────────────────────────────────────────────────────

  function audioUrl(url: string): string {
    try {
      if (new URL(url).hostname === 'media.hardwax.com')
        return `/api/audio-proxy?url=${encodeURIComponent(url)}`
    } catch {}
    return url
  }

  function _playAudio(release: any, idx: number): void {
    const urls = getTracks(release)
    if (!urls.length) return
    activeId.value      = release.id
    activeTrack.value   = idx
    activeRelease.value = release
    const url = audioUrl(urls[idx])
    if (!url) return
    if (!audioEl) audioEl = new Audio()
    audioEl.volume           = volume.value
    audioEl.onended          = autoNext
    audioEl.ontimeupdate     = () => { currentTime.value = audioEl!.currentTime }
    audioEl.onloadedmetadata = () => { duration.value = audioEl!.duration || 0 }
    audioEl.src = url
    audioEl.play().then(() => { isPlaying.value = true }).catch(() => {})
  }

  function _stopAudio(): void {
    audioEl?.pause()
    if (audioEl) audioEl.src = ''
    currentTime.value = 0
    duration.value    = 0
  }

  function seek(time: number): void {
    if (!audioEl) return
    audioEl.currentTime = time
    currentTime.value   = time
  }

  function setVolume(val: number): void {
    volume.value = val
    if (audioEl) audioEl.volume = val
  }

  // ── YouTube backend ─────────────────────────────────────────────────────────

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
          isPlaying.value = e.data === 1
          if (e.data === 0) autoNext()
        },
      },
    })
  }

  async function _playVideo(release: any, idx: number): Promise<void> {
    const vid = extractVideoId(getVideos(release)[idx]?.uri)
    if (!vid) return
    activeId.value      = String(release.id)
    activeTrack.value   = idx
    activeRelease.value = release
    ytOpen.value        = true
    ytPending           = vid
    if (!ytPlayer) {
      await nextTick()
      await ensurePlayer()
    } else {
      ytPlayer.loadVideoById(vid)
    }
  }

  function _stopVideo(): void {
    ytPlayer?.stopVideo()
    ytOpen.value = false
  }

  // ── Cross-release autoplay (shared) ─────────────────────────────────────────

  function autoNext(): void {
    if (!activeRelease.value) return
    const items = getItems(activeRelease.value)
    if (activeTrack.value + 1 < items.length) {
      _setTrack(activeRelease.value, activeTrack.value + 1)
      return
    }
    const ci = releaseList.value.findIndex((r: any) => r.id === activeRelease.value!.id)
    for (let i = ci + 1; i < releaseList.value.length; i++) {
      if (getItems(releaseList.value[i]).length) { _setTrack(releaseList.value[i], 0); return }
    }
    isPlaying.value = false
  }

  function _setTrack(release: any, idx: number): void {
    if (mode.value === 'audio') _playAudio(release, idx)
    else if (mode.value === 'video') _playVideo(release, idx)
  }

  // ── Public play API ─────────────────────────────────────────────────────────

  function playAudio(release: any, idx: number): void {
    if (mode.value === 'video') _stopVideo()
    mode.value = 'audio'
    _playAudio(release, idx)
  }

  async function playVideo(release: any, idx: number): Promise<void> {
    if (mode.value === 'audio') _stopAudio()
    mode.value = 'video'
    await _playVideo(release, idx)
  }

  // ── Tile clicks ─────────────────────────────────────────────────────────────

  function tileClickAudio(release: any): void {
    if (activeId.value === release.id && mode.value === 'audio') {
      if (audioEl?.paused) { audioEl.play().catch(() => {}); isPlaying.value = true }
      else                 { audioEl?.pause();                isPlaying.value = false }
      return
    }
    playAudio(release, 0)
  }

  function tileClickVideo(release: any): void {
    if (activeId.value === String(release.id) && mode.value === 'video' && ytOpen.value) {
      toggle()
      return
    }
    if (getVideos(release).length) playVideo(release, 0)
  }

  // ── Shared navigation ───────────────────────────────────────────────────────

  function prevTrack(e?: Event): void {
    e?.stopPropagation()
    if (!activeRelease.value) return
    if (activeTrack.value > 0) { _setTrack(activeRelease.value, activeTrack.value - 1); return }
    const ci = releaseList.value.findIndex((r: any) => r.id === activeRelease.value!.id)
    for (let i = ci - 1; i >= 0; i--) {
      const items = getItems(releaseList.value[i])
      if (items.length) { _setTrack(releaseList.value[i], items.length - 1); return }
    }
  }

  function nextTrack(e?: Event): void {
    e?.stopPropagation()
    if (!activeRelease.value) return
    const items = getItems(activeRelease.value)
    if (activeTrack.value < items.length - 1) { _setTrack(activeRelease.value, activeTrack.value + 1); return }
    const ci = releaseList.value.findIndex((r: any) => r.id === activeRelease.value!.id)
    for (let i = ci + 1; i < releaseList.value.length; i++) {
      if (getItems(releaseList.value[i]).length) { _setTrack(releaseList.value[i], 0); return }
    }
  }

  function dotClick(release: any, idx: number, e: Event): void {
    e.stopPropagation()
    if (idx >= 0) _setTrack(release, idx)
  }

  const canPrev = computed(() => {
    if (!activeRelease.value) return false
    if (activeTrack.value > 0) return true
    const ci = releaseList.value.findIndex((r: any) => r.id === activeRelease.value!.id)
    return releaseList.value.slice(0, ci).some((r: any) => getItems(r).length > 0)
  })

  const canNext = computed(() => {
    if (!activeRelease.value) return false
    if (activeTrack.value < getItems(activeRelease.value).length - 1) return true
    const ci = releaseList.value.findIndex((r: any) => r.id === activeRelease.value!.id)
    return releaseList.value.slice(ci + 1).some((r: any) => getItems(r).length > 0)
  })

  // ── YouTube controls ────────────────────────────────────────────────────────

  function toggle(): void {
    if (!ytPlayer) return
    isPlaying.value ? ytPlayer.pauseVideo() : ytPlayer.playVideo()
  }

  function close(): void {
    ytPlayer?.pauseVideo()
    ytOpen.value = false
  }

  // ── Dots ────────────────────────────────────────────────────────────────────

  function computeDots(n: number, s: number, max = 5) {
    if (n <= max) {
      return Array.from({ length: n }, (_: any, i: number) => ({ index: i, small: false, selected: i === s }))
    }
    const half = Math.floor(max / 2)
    let start  = s - half
    let end    = start + max - 1
    if (start < 0) { start = 0;   end = max - 1 }
    if (end >= n)  { end = n - 1; start = n - max }
    return Array.from({ length: max }, (_: any, i: number) => {
      const idx  = start + i
      const over = (start > 0 && i === 0) || (end < n - 1 && i === max - 1)
      if (over) return { index: -1, small: true, selected: false }
      return { index: idx, small: false, selected: idx === s }
    })
  }

  // ── Stop all ────────────────────────────────────────────────────────────────

  function stopAll(): void {
    _stopAudio()
    ytPlayer?.pauseVideo()
    ytPending           = null
    ytOpen.value        = false
    isPlaying.value     = false
    activeId.value      = null
    activeRelease.value = null
    activeTrack.value   = 0
    mode.value          = null
  }

  return {
    // Shared state
    activeId, activeTrack, isPlaying, mode, releaseList, activeRelease,
    // Audio progress / volume
    currentTime, duration, volume, seek, setVolume,
    // Audio
    getTracks, getTrackNames,
    playAudio, tileClickAudio,
    // YouTube
    ytOpen,
    getVideos, playVideo, tileClickVideo,
    toggle, close,
    // Shared navigation
    prevTrack, nextTrack, dotClick,
    canPrev, canNext,
    computeDots,
    stopAll,
  }
}
