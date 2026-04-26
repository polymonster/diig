<script setup>
import { useFirebaseAuth, useCurrentUser } from 'vuefire'

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

function closeAll() { menuOpen.value = false; settingsOpen.value = false }
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
</style>
