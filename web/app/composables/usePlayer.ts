import type { Release } from '~/utils/release'

// The bottom-bar player. Module-level singletons, one player per browser tab
// (safe with ssr: false).
//
// Two backends behind one interface:
//   audio — store snippet mp3s (release.track_urls) through an <audio> element
//   video — YouTube clips (release.videos, discogs results) through the
//           iframe API, rendered offscreen by PlayerBar
//
// The page showing releases sets `releaseList` so playback can run on from one
// release into the next.

type Mode = 'audio' | 'video'

const activeRelease = ref<Release | null>(null)
const activeTrack   = ref(0)
const isPlaying     = ref(false)
const mode          = ref<Mode | null>(null)
const releaseList   = ref<Release[]>([])

// audio progress / volume
const currentTime = ref(0)
const duration    = ref(0)
const volume      = ref(1)

let audioEl: HTMLAudioElement | null = null

let ytPlayer: any = null
let ytPending: string | null = null

const activeId = computed(() => activeRelease.value ? String(activeRelease.value.id) : null)

export function usePlayer() {

  // ── Items ───────────────────────────────────────────────────────────────────

  function getTracks(release: Release): string[]     { return toArray(release?.track_urls) }
  function getTrackNames(release: Release): string[] { return toArray(release?.track_names) }
  function getVideos(release: Release)               { return release?.videos ?? [] }

  // what the current mode plays from a release
  function getItems(release: Release): unknown[] {
    if (mode.value === 'audio') return getTracks(release)
    if (mode.value === 'video') return getVideos(release)
    return []
  }

  // name of the item playing, or of track idx on a release
  function itemName(release: Release, idx: number): string {
    if (mode.value === 'video') return getVideos(release)[idx]?.title || ''
    return getTrackNames(release)[idx] || `Track ${idx + 1}`
  }

  function isActive(release: Release) {
    return activeId.value === String(release.id)
  }

  // ── Audio backend ───────────────────────────────────────────────────────────

  // hardwax doesn't send CORS headers, so its audio goes through our proxy
  function audioUrl(url: string): string {
    try {
      if (new URL(url).hostname === 'media.hardwax.com')
        return `/api/audio-proxy?url=${encodeURIComponent(url)}`
    } catch {}
    return url
  }

  function startAudio(release: Release, idx: number) {
    const url = getTracks(release)[idx]
    if (!url) return
    activeRelease.value = release
    activeTrack.value   = idx
    if (!audioEl) {
      audioEl = new Audio()
      audioEl.onended          = () => { if (!nextTrack()) isPlaying.value = false }
      audioEl.ontimeupdate     = () => { currentTime.value = audioEl!.currentTime }
      audioEl.onloadedmetadata = () => { duration.value = audioEl!.duration || 0 }
    }
    audioEl.volume = volume.value
    audioEl.src    = audioUrl(url)
    audioEl.play().then(() => { isPlaying.value = true }).catch(() => {})
  }

  function stopAudio() {
    audioEl?.pause()
    if (audioEl) audioEl.src = ''
    currentTime.value = 0
    duration.value    = 0
  }

  function seek(time: number) {
    if (!audioEl) return
    audioEl.currentTime = time
    currentTime.value   = time
  }

  function setVolume(val: number) {
    volume.value = val
    if (audioEl) audioEl.volume = val
  }

  // ── YouTube backend ─────────────────────────────────────────────────────────

  function extractVideoId(url: string | undefined): string | null {
    if (!url) return null
    const m = url.match(/[?&]v=([^&#]+)/) || url.match(/youtu\.be\/([^?&#]+)/)
    return m?.[1] ?? null
  }

  // load the iframe api once and create the player in PlayerBar's #yt-iframe
  async function ensureYtPlayer() {
    if (ytPlayer) return
    const w = window as any
    await new Promise<void>(resolve => {
      if (w.YT?.Player) { resolve(); return }
      w.onYouTubeIframeAPIReady = resolve
      if (!document.querySelector('script[src*="youtube.com/iframe_api"]')) {
        const s = document.createElement('script')
        s.src = 'https://www.youtube.com/iframe_api'
        document.head.appendChild(s)
      }
    })
    ytPlayer = new w.YT.Player('yt-iframe', {
      height: '68', width: '120', videoId: '',
      playerVars: { autoplay: 1, controls: 0, rel: 0, modestbranding: 1, iv_load_policy: 3, playsinline: 1 },
      events: {
        onReady(e: any) { if (ytPending) e.target.loadVideoById(ytPending) },
        onStateChange(e: any) {
          // 1 playing, 0 ended
          isPlaying.value = e.data === 1
          if (e.data === 0 && !nextTrack()) isPlaying.value = false
        },
      },
    })
  }

  async function startVideo(release: Release, idx: number) {
    const vid = extractVideoId(getVideos(release)[idx]?.uri)
    if (!vid) return
    activeRelease.value = release
    activeTrack.value   = idx
    ytPending           = vid
    if (ytPlayer) ytPlayer.loadVideoById(vid)
    else await ensureYtPlayer()
  }

  // ── Play / pause ────────────────────────────────────────────────────────────

  function play(release: Release, idx: number, newMode: Mode) {
    if (mode.value !== newMode) {
      if (mode.value === 'audio') stopAudio()
      if (mode.value === 'video') ytPlayer?.pauseVideo()
      mode.value = newMode
    }
    if (newMode === 'audio') startAudio(release, idx)
    else startVideo(release, idx)
  }

  const playAudio = (release: Release, idx = 0) => play(release, idx, 'audio')
  const playVideo = (release: Release, idx = 0) => play(release, idx, 'video')

  function pause() {
    if (mode.value === 'audio') audioEl?.pause()
    if (mode.value === 'video') ytPlayer?.pauseVideo()
    isPlaying.value = false
  }

  function resume() {
    if (mode.value === 'audio') audioEl?.play().catch(() => {})
    if (mode.value === 'video') ytPlayer?.playVideo()
    isPlaying.value = true
  }

  function togglePlay() {
    if (!activeRelease.value) return
    isPlaying.value ? pause() : resume()
  }

  // a tile click: pause / resume when it's the release playing, otherwise
  // start it from its first item
  function toggleRelease(release: Release, newMode: Mode) {
    if (isActive(release) && mode.value === newMode) togglePlay()
    else play(release, 0, newMode)
  }

  // ── Track navigation ────────────────────────────────────────────────────────

  // the item `dir` steps (+1 / -1) from the one playing, running on into the
  // neighbouring releases in releaseList and skipping any with nothing to play
  function step(dir: 1 | -1): { release: Release, idx: number } | null {
    const cur = activeRelease.value
    if (!cur) return null
    const idx = activeTrack.value + dir
    if (idx >= 0 && idx < getItems(cur).length) return { release: cur, idx }

    const list = releaseList.value
    const ci   = list.findIndex(r => String(r.id) === String(cur.id))
    for (let i = ci + dir; i >= 0 && i < list.length; i += dir) {
      const n = getItems(list[i]!).length
      if (n) return { release: list[i]!, idx: dir > 0 ? 0 : n - 1 }
    }
    return null
  }

  // returns false when there was nowhere to go
  function goTo(dir: 1 | -1): boolean {
    const s = step(dir)
    if (s) play(s.release, s.idx, mode.value!)
    return !!s
  }

  const prevTrack = () => goTo(-1)
  const nextTrack = () => goTo(1)

  const canPrev = computed(() => !!step(-1))
  const canNext = computed(() => !!step(1))

  // ── Stop ────────────────────────────────────────────────────────────────────

  function stopAll() {
    stopAudio()
    ytPlayer?.pauseVideo()
    ytPending           = null
    isPlaying.value     = false
    activeRelease.value = null
    activeTrack.value   = 0
    mode.value          = null
  }

  return {
    // state
    activeId, activeRelease, activeTrack, isPlaying, mode, releaseList,
    currentTime, duration, volume,
    // items
    getTracks, getTrackNames, getVideos, getItems, itemName, isActive,
    // control
    playAudio, playVideo, toggleRelease, togglePlay, seek, setVolume,
    prevTrack, nextTrack, canPrev, canNext,
    stopAll,
  }
}
