<script setup>
import { useFirebaseAuth, useCurrentUser } from 'vuefire'

const auth = useFirebaseAuth()
const user = useCurrentUser()
const DB   = 'https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app'

const menuOpen = useState('menuOpen', () => false)

const messages   = ref([])
const inputText  = ref('')
const msgList    = ref(null)
const error      = ref('')
let   pollTimer  = null

async function getToken() {
  return auth.currentUser?.getIdToken() ?? ''
}

async function loadMessages() {
  if (!auth.currentUser) return
  try {
    const token = await getToken()
    const data  = await fetch(`${DB}/chat.json?auth=${token}`).then(r => r.json())
    if (data && data.error) { error.value = data.error; return }
    error.value = ''
    if (!data || typeof data !== 'object') { messages.value = []; return }
    messages.value = Object.entries(data)
      .map(([k, v]) => ({ key: k, ...v }))
      .sort((a, b) => a.ts - b.ts)
      .slice(-80)
    scrollToBottom()
  } catch (e) {
    error.value = String(e)
  }
}

function startPolling() {
  loadMessages()
  pollTimer = setInterval(loadMessages, 4000)
}

function scrollToBottom() {
  nextTick(() => {
    if (msgList.value) msgList.value.scrollTop = msgList.value.scrollHeight
  })
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || !auth.currentUser) return
  inputText.value = ''
  const token = await getToken()
  const uid   = auth.currentUser.uid

  let name = auth.currentUser.email || 'anon'
  try {
    const userData = await fetch(`${DB}/users/${uid}.json?auth=${token}`).then(r => r.json())
    name = userData?.username || name
  } catch {}

  const res = await fetch(`${DB}/chat.json?auth=${token}`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ uid, name, text, ts: Date.now() }),
  })
  const result = await res.json()
  if (result.error) { error.value = result.error; return }
  await loadMessages()
}

function formatTime(ts) {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

watch(user, u => { if (u) startPolling() }, { immediate: true })

onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })
</script>

<template>
  <div class="page">
    <header class="header">
      <NuxtLink to="/" class="logo">diig</NuxtLink>
      <span class="page-title">chat</span>
      <div class="header-right">
        <NuxtLink to="/likes" class="likes-nav">
          <span class="fa">&#xf004;</span>
        </NuxtLink>
        <button class="burger-btn fa" @click="menuOpen = !menuOpen">&#xf0c9;</button>
      </div>
    </header>

    <main class="content">
      <div ref="msgList" class="msg-list">
        <p v-if="error" class="error">{{ error }}</p>
        <p v-else-if="!messages.length" class="empty">no messages yet</p>
        <div v-for="m in messages" :key="m.key" class="msg" :class="{ mine: m.uid === user?.uid }">
          <span class="msg-name">{{ m.name }}</span>
          <span class="msg-text">{{ m.text }}</span>
          <span class="msg-time">{{ formatTime(m.ts) }}</span>
        </div>
      </div>

      <div class="input-bar">
        <input
          v-model="inputText"
          class="msg-input"
          placeholder="say something..."
          @keydown.enter.prevent="sendMessage"
          spellcheck="false"
          autocomplete="off"
        />
        <button class="send-btn" @click="sendMessage" :disabled="!inputText.trim()">send</button>
      </div>
    </main>
  </div>
</template>

<style scoped>
@font-face {
  font-family: 'Cousine';
  src: url('/cousine-regular.ttf') format('truetype');
}

@font-face {
  font-family: 'FontAwesome';
  src: url('/fontawesome-webfont.ttf') format('truetype');
  font-weight: normal;
  font-style: normal;
}

* { font-family: 'Cousine', monospace; box-sizing: border-box; }

.fa {
  font-family: 'FontAwesome';
  font-style: normal;
  font-weight: normal;
  line-height: 1;
  -webkit-font-smoothing: antialiased;
}

.page { min-height: 100vh; display: flex; flex-direction: column; background: #f5f5f5; color: #0a0a0a; }

.header {
  display: flex;
  align-items: center;
  gap: 2rem;
  padding: 1rem 1.5rem;
  background: #fff;
  border-bottom: 1px solid #e0e0e0;
  position: sticky;
  top: 0;
  z-index: 10;
  flex-shrink: 0;
}

.logo {
  font-size: 1.1rem;
  letter-spacing: 0.1em;
  text-decoration: none;
  color: #0a0a0a;
}

.page-title { font-size: 0.8rem; color: #999; }

.header-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.9rem;
}

.likes-nav { font-size: 1rem; color: #ccc; text-decoration: none; transition: color 0.15s; }
.likes-nav:hover { color: #e03070; }

.content {
  flex: 1;
  display: flex;
  flex-direction: column;
  max-width: 720px;
  width: 100%;
  margin: 0 auto;
  padding: 0;
  height: calc(100vh - 57px);
}

.msg-list {
  flex: 1;
  overflow-y: auto;
  padding: 1rem 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.msg {
  display: flex;
  flex-direction: column;
  max-width: 75%;
  align-self: flex-start;
}

.msg.mine { align-self: flex-end; align-items: flex-end; }

.msg-name {
  font-size: 0.55rem;
  color: #aaa;
  margin-bottom: 2px;
}

.msg-text {
  font-size: 0.75rem;
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 3px;
  padding: 0.4rem 0.65rem;
  color: #0a0a0a;
  line-height: 1.4;
  word-break: break-word;
}

.msg.mine .msg-text {
  background: #0a0a0a;
  color: #fff;
  border-color: #0a0a0a;
}

.msg-time {
  font-size: 0.5rem;
  color: #ccc;
  margin-top: 2px;
}

.input-bar {
  display: flex;
  gap: 0.5rem;
  padding: 0.75rem 1.5rem;
  background: #fff;
  border-top: 1px solid #e0e0e0;
  flex-shrink: 0;
}

.msg-input {
  flex: 1;
  font-family: 'Cousine', monospace;
  font-size: 0.75rem;
  border: 1px solid #ddd;
  border-radius: 3px;
  padding: 0.4rem 0.6rem;
  outline: none;
  color: #333;
  background: #fafafa;
}

.msg-input:focus { border-color: #aaa; background: #fff; }

.send-btn {
  font-family: 'Cousine', monospace;
  font-size: 0.65rem;
  padding: 0.4rem 0.9rem;
  background: #0a0a0a;
  color: #fff;
  border: none;
  border-radius: 3px;
  cursor: pointer;
  white-space: nowrap;
}

.send-btn:disabled { opacity: 0.3; cursor: default; }

.empty { font-size: 0.75rem; color: #bbb; margin: 0; }
.error { font-size: 0.65rem; color: #c44; margin: 0; }
</style>
