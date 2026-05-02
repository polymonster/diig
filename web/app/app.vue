<script setup>
import { useFirebaseAuth, useCurrentUser } from 'vuefire'
import { artworkUrl } from '~/utils/artwork'

const auth = useFirebaseAuth()
const user = useCurrentUser()
const DB   = 'https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app'

const menuOpen     = useState('menuOpen',     () => false)
const settingsOpen = useState('settingsOpen', () => false)

function ls(key, fallback = '') { return localStorage.getItem(key) || fallback }

// ── Username ──────────────────────────────────────────────────────────────────

const username      = ref('')
const usernameInput = ref('')
const usernameSaved = ref(false)

watch(user, async u => {
  if (!u) return
  const token    = await auth.currentUser.getIdToken()
  const userData = await fetch(`${DB}/users/${u.uid}.json?auth=${token}`).then(r => r.json())
  const name     = userData?.username || ''
  username.value      = name || u.email
  usernameInput.value = name
}, { immediate: true })

async function saveUsername() {
  if (!auth.currentUser) return
  const token = await auth.currentUser.getIdToken()
  await fetch(`${DB}/users/${auth.currentUser.uid}/username.json?auth=${token}`, {
    method: 'PUT',
    body:   JSON.stringify(usernameInput.value),
  })
  username.value = usernameInput.value || user.value?.email || ''
  usernameSaved.value = true
  setTimeout(() => { usernameSaved.value = false }, 2000)
}

const discogsToken  = ref(ls('discogsToken'))
const discogsUser   = ref(ls('discogsUser'))
const discogsStatus = ref(discogsToken.value && discogsUser.value ? 'ok' : 'idle')

async function verifyDiscogs() {
  discogsStatus.value = 'checking'
  try {
    const res = await fetch('https://api.discogs.com/oauth/identity', {
      headers: { Authorization: `Discogs token=${discogsToken.value}` },
    })
    if (res.ok) {
      const data = await res.json()
      discogsUser.value   = data.username || ''
      discogsStatus.value = 'ok'
      localStorage.setItem('discogsToken', discogsToken.value)
      localStorage.setItem('discogsUser',  discogsUser.value)
    } else {
      discogsStatus.value = 'error'
    }
  } catch {
    discogsStatus.value = 'error'
  }
}

const showDebug = ref(ls('showDebug') === 'true')
watch(showDebug, val => localStorage.setItem('showDebug', String(val)))

const debugLogs = ref([])
function debugLog(type, msg) {
  debugLogs.value.unshift({ type, msg: String(msg).slice(0, 300), t: new Date().toISOString().slice(11,23) })
  if (debugLogs.value.length > 50) debugLogs.value.pop()
}

if (process.client) {
  const origError = console.error.bind(console)
  console.error = (...args) => { debugLog('err', args.join(' ')); origError(...args) }
  const origWarn = console.warn.bind(console)
  console.warn = (...args) => { debugLog('warn', args.join(' ')); origWarn(...args) }
  window.addEventListener('error', e => debugLog('exc', `${e.message} @ ${e.filename?.split('/').pop()}:${e.lineno}`))
  window.addEventListener('unhandledrejection', e => debugLog('rej', e.reason?.message || e.reason))
}

function closeAll() { menuOpen.value = false; settingsOpen.value = false }

// ── Player bar ────────────────────────────────────────────────────────────────

const { activeTrack, isPlaying, activeRelease, getTrackNames, tileClick, skipPrev, skipNext, canSkipPrev, canSkipNext } = useAudio()

function playerArt(release) { return artworkUrl(release) || '/white_label.jpg' }
function playerToggle() { if (activeRelease.value) tileClick(activeRelease.value) }
</script>

<template>
  <div>
    <NuxtPage />

    <div v-if="menuOpen" class="burger-backdrop" @click="closeAll" />
    <div v-if="menuOpen" class="burger-menu">
      <div v-if="user" class="menu-username">{{ username }}</div>
      <label class="menu-toggle">
        <span>Show Debug</span>
        <input type="checkbox" v-model="showDebug" />
      </label>
      <button class="menu-settings-btn" @click="settingsOpen = true; menuOpen = false">Settings</button>
    </div>

    <!-- Bottom player bar -->
    <div v-if="activeRelease" class="player-bar">
      <img
        :src="playerArt(activeRelease)"
        class="player-art"
        @error="e => e.target.src = '/white_label.jpg'"
      />
      <div class="player-info">
        <span class="player-artist">{{ activeRelease.artist }}</span>
        <span class="player-title">{{ activeRelease.title }}</span>
        <span v-if="getTrackNames(activeRelease)[activeTrack]" class="player-track">{{ getTrackNames(activeRelease)[activeTrack] }}</span>
      </div>
      <div class="player-controls">
        <button class="player-btn" :disabled="!canSkipPrev" @click="skipPrev()">&#8249;</button>
        <button class="player-btn play-btn" @click="playerToggle">
          <span v-if="isPlaying">&#9646;&#9646;</span>
          <span v-else>&#9654;</span>
        </button>
        <button class="player-btn" :disabled="!canSkipNext" @click="skipNext()">&#8250;</button>
      </div>
    </div>

    <div v-if="showDebug" class="debug-overlay">
      <div class="debug-bar">
        <span>debug</span>
        <button @click="debugLogs = []">clear</button>
      </div>
      <div v-for="(l, i) in debugLogs" :key="i" class="debug-line" :class="l.type">
        <span class="debug-t">{{ l.t }}</span> <span class="debug-type">{{ l.type }}</span> {{ l.msg }}
      </div>
    </div>

    <div v-if="settingsOpen" class="settings-overlay" @click.self="settingsOpen = false">
      <div class="settings-panel">
        <div class="settings-header">
          <span>Settings</span>
          <button @click="settingsOpen = false">&#10005;</button>
        </div>
        <div class="settings-section">
          <label class="settings-label">Username</label>
          <div class="settings-row">
            <input
              v-model="usernameInput"
              type="text"
              class="settings-input"
              placeholder="your username"
              spellcheck="false"
              autocomplete="off"
            />
            <button class="settings-verify" @click="saveUsername" :disabled="!usernameInput">
              {{ usernameSaved ? '✓' : 'save' }}
            </button>
          </div>
        </div>
        <div class="settings-section">
          <label class="settings-label">Discogs Token</label>
          <p class="settings-hint">Discogs &rsaquo; Settings &rsaquo; Developers &rsaquo; Generate Token</p>
          <div class="settings-row">
            <input
              v-model="discogsToken"
              type="text"
              class="settings-input"
              placeholder="paste token here"
              spellcheck="false"
              autocomplete="off"
            />
            <button
              class="settings-verify"
              @click="verifyDiscogs"
              :disabled="!discogsToken || discogsStatus === 'checking'"
            >{{ discogsStatus === 'checking' ? '...' : 'verify' }}</button>
          </div>
          <span v-if="discogsStatus === 'ok'"    class="settings-ok">&#10003; {{ discogsUser }}</span>
          <span v-if="discogsStatus === 'error'" class="settings-err">invalid token</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style>
@font-face {
  font-family: 'FontAwesome';
  src: url('/fontawesome-webfont.ttf') format('truetype');
  font-weight: normal;
  font-style: normal;
}

html, body {
  touch-action: manipulation;
  overscroll-behavior: none;
}

.fa {
  font-family: 'FontAwesome';
  font-style: normal;
  font-weight: normal;
  line-height: 1;
  -webkit-font-smoothing: antialiased;
}

.burger-btn {
  background: none;
  border: none;
  font-size: 1rem;
  cursor: pointer;
  color: #bbb;
  padding: 0;
  line-height: 1;
}
.burger-btn:hover { color: #555; }

.burger-backdrop {
  position: fixed;
  inset: 0;
  z-index: 150;
}

.burger-menu {
  position: fixed;
  top: 3.4rem;
  right: 0.75rem;
  z-index: 160;
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  min-width: 180px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  font-family: 'Cousine', monospace;
}

.menu-username {
  padding: 0.55rem 0.9rem;
  font-size: 0.6rem;
  color: #aaa;
  border-bottom: 1px solid #f0f0f0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.menu-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.45rem 0.9rem;
  font-size: 0.65rem;
  cursor: pointer;
  color: #333;
  border-bottom: 1px solid #f0f0f0;
  gap: 1rem;
}

.menu-settings-btn {
  background: none;
  border: none;
  padding: 0.45rem 0.9rem;
  font-size: 0.65rem;
  font-family: 'Cousine', monospace;
  text-align: left;
  cursor: pointer;
  color: #333;
}
.menu-settings-btn:hover { background: #f9f9f9; }

.settings-overlay {
  position: fixed;
  inset: 0;
  z-index: 300;
  background: rgba(0,0,0,0.3);
  display: flex;
  align-items: center;
  justify-content: center;
}

.settings-panel {
  background: #fff;
  border-radius: 5px;
  width: min(90vw, 360px);
  padding: 1.25rem 1.5rem 1.5rem;
  box-shadow: 0 8px 32px rgba(0,0,0,0.15);
  font-family: 'Cousine', monospace;
}

.settings-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.25rem;
  font-size: 0.75rem;
  color: #333;
}
.settings-header button {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.85rem;
  color: #aaa;
  padding: 0;
  line-height: 1;
}
.settings-header button:hover { color: #555; }

.settings-label {
  display: block;
  font-size: 0.6rem;
  color: #aaa;
  margin-bottom: 0.25rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.settings-hint {
  font-size: 0.55rem;
  color: #bbb;
  margin: 0 0 0.5rem;
}

.settings-row {
  display: flex;
  gap: 0.4rem;
}

.settings-input {
  flex: 1;
  padding: 0.35rem 0.5rem;
  font-size: 0.65rem;
  font-family: 'Cousine', monospace;
  border: 1px solid #ddd;
  border-radius: 3px;
  outline: none;
  color: #333;
}
.settings-input:focus { border-color: #aaa; }

.settings-verify {
  padding: 0.35rem 0.65rem;
  font-size: 0.6rem;
  font-family: 'Cousine', monospace;
  background: #0a0a0a;
  color: #fff;
  border: none;
  border-radius: 3px;
  cursor: pointer;
  white-space: nowrap;
}
.settings-verify:disabled { opacity: 0.4; cursor: default; }

.settings-ok  { display: block; font-size: 0.6rem; color: #4a9; margin-top: 0.4rem; }
.settings-err { display: block; font-size: 0.6rem; color: #c44; margin-top: 0.4rem; }

/* Player bar */
.player-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 200;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.5rem 1rem;
  background: #fff;
  border-top: 1px solid #e0e0e0;
  box-shadow: 0 -2px 12px rgba(0,0,0,0.06);
  font-family: 'Cousine', monospace;
}

.player-art {
  width: 40px;
  height: 40px;
  object-fit: cover;
  flex-shrink: 0;
}

.player-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.player-artist {
  font-size: 0.65rem;
  color: #0a0a0a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.player-title {
  font-size: 0.58rem;
  color: #888;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.player-track {
  font-size: 0.55rem;
  color: #cc4d00;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.player-controls {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  flex-shrink: 0;
}

.player-btn {
  background: none;
  border: none;
  font-family: 'Cousine', monospace;
  font-size: 1.2rem;
  color: #aaa;
  cursor: pointer;
  padding: 0.2rem 0.35rem;
  line-height: 1;
  transition: color 0.1s;
}

.player-btn:not(:disabled):hover { color: #333; }
.player-btn:disabled { opacity: 0.25; cursor: default; }

.play-btn {
  font-size: 1rem;
  color: #0a0a0a;
  padding: 0.2rem 0.5rem;
}
.play-btn:hover { color: #cc4d00; }

.debug-overlay {
  position: fixed;
  bottom: 60px;
  left: 0;
  right: 0;
  max-height: 40vh;
  overflow-y: auto;
  background: rgba(0,0,0,0.88);
  z-index: 9999;
  font-family: monospace;
  font-size: 10px;
  color: #ccc;
}
.debug-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 3px 8px;
  background: #111;
  color: #888;
  position: sticky;
  top: 0;
}
.debug-bar button {
  background: none;
  border: 1px solid #444;
  color: #888;
  font-size: 10px;
  padding: 1px 6px;
  cursor: pointer;
}
.debug-line {
  padding: 2px 8px;
  border-bottom: 1px solid #222;
  word-break: break-all;
  white-space: pre-wrap;
}
.debug-line.err, .debug-line.exc, .debug-line.rej { color: #f88; }
.debug-line.warn { color: #fa8; }
.debug-t    { color: #555; }
.debug-type { color: #88f; margin-right: 4px; }
</style>
