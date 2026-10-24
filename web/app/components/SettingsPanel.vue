<script setup lang="ts">
// the settings dialog, opened from the menu: username and discogs token
const settingsOpen = useState('settingsOpen', () => false)

const { username, saveUsername } = useProfile()
const discogs = useDiscogs()

// edited copies, so typing doesn't change anything until saved
const usernameInput = ref(username.value)
const tokenInput    = ref(discogs.token.value)
const usernameSaved = ref(false)

watch(settingsOpen, open => {
  if (!open) return
  usernameInput.value = username.value
  tokenInput.value    = discogs.token.value
})

async function onSaveUsername() {
  if (!await saveUsername(usernameInput.value)) return
  usernameSaved.value = true
  setTimeout(() => { usernameSaved.value = false }, 2000)
}
</script>

<template>
  <div v-if="settingsOpen" class="overlay" @click.self="settingsOpen = false">
    <div class="panel">
      <div class="header">
        <span>Settings</span>
        <button class="close" @click="settingsOpen = false">&#10005;</button>
      </div>

      <div class="section">
        <label class="label">Username</label>
        <div class="row">
          <input
            v-model="usernameInput"
            type="text"
            class="input"
            placeholder="your username"
            spellcheck="false"
            autocomplete="off"
          >
          <button class="btn-sm" :disabled="!usernameInput" @click="onSaveUsername">
            {{ usernameSaved ? '✓' : 'save' }}
          </button>
        </div>
      </div>

      <div class="section">
        <label class="label">Discogs Token</label>
        <p class="hint">Discogs &rsaquo; Settings &rsaquo; Developers &rsaquo; Generate Token</p>
        <div class="row">
          <input
            v-model="tokenInput"
            type="text"
            class="input"
            placeholder="paste token here"
            spellcheck="false"
            autocomplete="off"
          >
          <button
            class="btn-sm"
            :disabled="!tokenInput || discogs.status.value === 'checking'"
            @click="discogs.verify(tokenInput)"
          >{{ discogs.status.value === 'checking' ? '...' : 'verify' }}</button>
        </div>
        <span v-if="discogs.status.value === 'ok'" class="ok">&#10003; {{ discogs.user.value }}</span>
        <span v-if="discogs.status.value === 'error'" class="err">invalid token</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 300;
  background: rgba(0, 0, 0, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
}

.panel {
  background: var(--panel);
  border-radius: 5px;
  width: min(90vw, 360px);
  padding: 1.25rem 1.5rem 1.5rem;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.25rem;
  font-size: 0.75rem;
  color: #333;
}

.close {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.85rem;
  color: #aaa;
  padding: 0;
  line-height: 1;
}
.close:hover { color: #555; }

.section + .section { margin-top: 1rem; }

.label {
  display: block;
  font-size: 0.6rem;
  color: #aaa;
  margin-bottom: 0.25rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.hint {
  font-size: 0.55rem;
  color: #bbb;
  margin: 0 0 0.5rem;
}

.row {
  display: flex;
  gap: 0.4rem;
}

.input {
  flex: 1;
  padding: 0.35rem 0.5rem;
  font-size: 0.65rem;
  border: 1px solid #ddd;
  border-radius: 3px;
  outline: none;
  color: #333;
}
.input:focus { border-color: #aaa; }

.ok, .err {
  display: block;
  font-size: 0.6rem;
  margin-top: 0.4rem;
}
.ok  { color: #4a9; }
.err { color: #c44; }
</style>
