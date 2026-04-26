// Module-level singletons — one instance per browser tab (safe with ssr: false)
const activeId      = ref<string | null>(null)
const activeTrack   = ref<number>(0)
const isPlaying     = ref<boolean>(false)
const releaseList   = ref<any[]>([])  // current page's ordered flat list for cross-release autoplay
const activeRelease = ref<any | null>(null)
let audioEl: HTMLAudioElement | null = null

export function useAudio() {
  function toArray(val: any): any[] {
    if (!val) return []
    return Array.isArray(val) ? val : Object.values(val)
  }

  function getTracks(release: any): any[]     { return toArray(release.track_urls) }
  function getTrackNames(release: any): any[] { return toArray(release.track_names) }

  function setTrack(release: any, idx: number) {
    const urls = getTracks(release)
    if (!urls.length) return
    activeId.value      = release.id
    activeTrack.value   = idx
    activeRelease.value = release
    const url = urls[idx]
    if (!url) return
    if (!audioEl) audioEl = new Audio()
    audioEl.onended = () => {
      const nextTrackIdx = activeTrack.value + 1
      if (nextTrackIdx < getTracks(release).length) {
        setTrack(release, nextTrackIdx)
        return
      }
      // advance to next release with audio in the current page's list
      const currentIdx = releaseList.value.findIndex((r: any) => r.id === release.id)
      for (let i = currentIdx + 1; i < releaseList.value.length; i++) {
        const candidate = releaseList.value[i]
        if (getTracks(candidate).length) { setTrack(candidate, 0); return }
      }
      isPlaying.value = false
    }
    audioEl.src = url
    audioEl.play().then(() => { isPlaying.value = true }).catch(() => {})
  }

  function tileClick(release: any) {
    if (activeId.value === release.id) {
      if (audioEl?.paused) { audioEl.play().catch(() => {}); isPlaying.value = true }
      else                 { audioEl?.pause();                isPlaying.value = false }
      return
    }
    setTrack(release, 0)
  }

  function prevTrack(release: any, e: Event) {
    e.stopPropagation()
    if (activeTrack.value > 0) setTrack(release, activeTrack.value - 1)
  }

  function nextTrack(release: any, e: Event) {
    e.stopPropagation()
    const urls = getTracks(release)
    if (activeTrack.value < urls.length - 1) setTrack(release, activeTrack.value + 1)
  }

  function dotClick(release: any, dot: any, e: Event) {
    e.stopPropagation()
    if (dot.index >= 0) setTrack(release, dot.index)
  }

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

  function skipPrev() {
    if (!activeRelease.value) return
    if (activeTrack.value > 0) { setTrack(activeRelease.value, activeTrack.value - 1); return }
    const ci = releaseList.value.findIndex((r: any) => r.id === activeRelease.value.id)
    for (let i = ci - 1; i >= 0; i--) {
      const tracks = getTracks(releaseList.value[i])
      if (tracks.length) { setTrack(releaseList.value[i], tracks.length - 1); return }
    }
  }

  function skipNext() {
    if (!activeRelease.value) return
    const tracks = getTracks(activeRelease.value)
    if (activeTrack.value < tracks.length - 1) { setTrack(activeRelease.value, activeTrack.value + 1); return }
    const ci = releaseList.value.findIndex((r: any) => r.id === activeRelease.value.id)
    for (let i = ci + 1; i < releaseList.value.length; i++) {
      if (getTracks(releaseList.value[i]).length) { setTrack(releaseList.value[i], 0); return }
    }
  }

  const canSkipPrev = computed(() => {
    if (!activeRelease.value) return false
    if (activeTrack.value > 0) return true
    const ci = releaseList.value.findIndex((r: any) => r.id === activeRelease.value.id)
    return releaseList.value.slice(0, ci).some((r: any) => getTracks(r).length > 0)
  })

  const canSkipNext = computed(() => {
    if (!activeRelease.value) return false
    if (activeTrack.value < getTracks(activeRelease.value).length - 1) return true
    const ci = releaseList.value.findIndex((r: any) => r.id === activeRelease.value.id)
    return releaseList.value.slice(ci + 1).some((r: any) => getTracks(r).length > 0)
  })

  function stopAll() {
    audioEl?.pause()
    if (audioEl) audioEl.src = ''
    isPlaying.value     = false
    activeId.value      = null
    activeRelease.value = null
  }

  return {
    activeId, activeTrack, isPlaying, releaseList, activeRelease,
    tileClick, setTrack, prevTrack, nextTrack, skipPrev, skipNext, canSkipPrev, canSkipNext, dotClick,
    computeDots, getTracks, getTrackNames, stopAll,
  }
}
