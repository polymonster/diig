<script setup lang="ts">
import { useFirebaseAuth, useCurrentUser } from 'vuefire'
import {
  signInWithEmailAndPassword,
  browserLocalPersistence,
  setPersistence,
  sendPasswordResetEmail
} from 'firebase/auth'

const auth = useFirebaseAuth()
const user = useCurrentUser()
const router = useRouter()

// ── Tabs ─────────────────────────────────────────────────────────────────────
type Tab = 'login' | 'register'
const tab = ref<Tab>('login')

// ── Login ─────────────────────────────────────────────────────────────────────
const email = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const success = ref('')
const showForgotPassword = ref(false)
const resetLoading = ref(false)

const isValidEmail = computed(() => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value))
const isFormValid = computed(() => isValidEmail.value && password.value.length >= 6)

watch(user, (newUser) => {
  if (newUser) router.push('/')
}, { immediate: true })

function switchTab(t: Tab) {
  tab.value = t
  error.value = ''
  success.value = ''
  showForgotPassword.value = false
}

const handleEmailLogin = async () => {
  if (!auth || !isFormValid.value) return
  loading.value = true
  error.value = ''
  try {
    await setPersistence(auth, browserLocalPersistence)
    await signInWithEmailAndPassword(auth, email.value, password.value)
  } catch (err: any) {
    error.value = getErrorMessage(err.code)
    password.value = ''
  } finally {
    loading.value = false
  }
}

const handlePasswordReset = async () => {
  if (!auth || !isValidEmail.value) return
  resetLoading.value = true
  error.value = ''
  success.value = ''
  try {
    await sendPasswordResetEmail(auth, email.value)
    success.value = 'Reset link sent — check your inbox.'
    setTimeout(() => {
      showForgotPassword.value = false
      success.value = ''
    }, 3000)
  } catch (err: any) {
    error.value = getPasswordResetErrorMessage(err.code)
  } finally {
    resetLoading.value = false
  }
}

const getErrorMessage = (code: string) => ({
  'auth/invalid-email': 'Invalid email address.',
  'auth/user-disabled': 'This account has been disabled.',
  'auth/user-not-found': 'Invalid email or password.',
  'auth/wrong-password': 'Invalid email or password.',
  'auth/invalid-credential': 'Invalid email or password.',
  'auth/too-many-requests': 'Too many attempts — try again later.',
} as Record<string, string>)[code] ?? 'Something went wrong, please try again.'

const getPasswordResetErrorMessage = (code: string) => ({
  'auth/invalid-email': 'Invalid email address.',
  'auth/user-not-found': 'No account found with that email.',
  'auth/too-many-requests': 'Too many requests — try again later.',
} as Record<string, string>)[code] ?? 'Failed to send reset email.'

// ── Register interest ─────────────────────────────────────────────────────────
const regEmail = ref('')
const regMessage = ref('')
const regLoading = ref(false)
const regDone = ref(false)

const isRegEmailValid = computed(() => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(regEmail.value))

const handleRegister = async () => {
  if (!isRegEmailValid.value) return
  regLoading.value = true
  error.value = ''
  try {
    const res = await fetch('/api/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: regEmail.value, message: regMessage.value }),
    })
    if (!res.ok) {
      const data = await res.json() as { message?: string }
      throw new Error(data.message ?? 'Registration failed.')
    }
    regDone.value = true
  } catch (err: any) {
    error.value = err.message ?? 'Something went wrong, please try again.'
  } finally {
    regLoading.value = false
  }
}
</script>

<template>
  <div class="page">
    <div class="card">
      <h1 class="title">diig</h1>

      <div class="tabs">
        <button :class="['tab', { active: tab === 'login' }]" @click="switchTab('login')">sign in</button>
        <button :class="['tab', { active: tab === 'register' }]" @click="switchTab('register')">register interest</button>
      </div>

      <div v-if="error" class="msg error">{{ error }}</div>
      <div v-if="success" class="msg success">{{ success }}</div>

      <!-- ── Sign in ── -->
      <template v-if="tab === 'login'">
        <form v-if="!showForgotPassword" @submit.prevent="handleEmailLogin">
          <input v-model="email" type="email" placeholder="email" autocomplete="email" required class="field" />
          <input v-model="password" type="password" placeholder="password" autocomplete="current-password" required class="field" />
          <div class="actions">
            <button type="submit" :disabled="loading || !isFormValid" class="btn">
              {{ loading ? 'signing in...' : 'sign in' }}
            </button>
            <button type="button" class="ghost" @click="showForgotPassword = true">forgot password</button>
          </div>
        </form>

        <form v-else @submit.prevent="handlePasswordReset">
          <input v-model="email" type="email" placeholder="email" autocomplete="email" required class="field" />
          <div class="actions">
            <button type="submit" :disabled="resetLoading || !isValidEmail" class="btn">
              {{ resetLoading ? 'sending...' : 'send reset link' }}
            </button>
            <button type="button" class="ghost" @click="showForgotPassword = false">back to sign in</button>
          </div>
        </form>
      </template>

      <!-- ── Register interest ── -->
      <template v-else>
        <div v-if="regDone" class="msg success">
          Thanks — we'll be in touch.
        </div>
        <form v-else @submit.prevent="handleRegister">
          <input v-model="regEmail" type="email" placeholder="email" autocomplete="email" required class="field" />
          <textarea
            v-model="regMessage"
            placeholder="tell us about yourself, or paste an invite code"
            class="field textarea"
            rows="4"
          />
          <div class="actions">
            <button type="submit" :disabled="regLoading || !isRegEmailValid" class="btn">
              {{ regLoading ? 'submitting...' : 'register interest' }}
            </button>
          </div>
        </form>
      </template>

      <div class="footer">
        <NuxtLink to="/faq" class="faq-link">FAQ</NuxtLink>
      </div>
    </div>
  </div>
</template>

<style scoped>
@font-face {
  font-family: 'Cousine';
  src: url('/cousine-regular.ttf') format('truetype');
  font-weight: normal;
  font-style: normal;
}

* { font-family: 'Cousine', monospace; }

.page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f5f5;
}

.card {
  width: 100%;
  max-width: 400px;
  padding: 2.5rem;
}

.title {
  font-size: 2rem;
  color: #0a0a0a;
  margin: 0 0 1.5rem;
  letter-spacing: 0.05em;
}

.tabs {
  display: flex;
  gap: 0;
  margin-bottom: 1.75rem;
  border-bottom: 1px solid #e0e0e0;
}

.tab {
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  padding: 0.4rem 0;
  margin-right: 1.5rem;
  font-family: 'Cousine', monospace;
  font-size: 0.8rem;
  color: #aaa;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}

.tab.active {
  color: #0a0a0a;
  border-bottom-color: #0a0a0a;
}

.tab:not(.active):hover { color: #666; }

.field {
  display: block;
  width: 100%;
  padding: 0.9rem 1rem;
  margin-bottom: 0.75rem;
  background: #fff;
  border: 1px solid #ccc;
  color: #0a0a0a;
  font-family: 'Cousine', monospace;
  font-size: 1rem;
  box-sizing: border-box;
  outline: none;
  transition: border-color 0.15s;
  resize: none;
}

.field::placeholder { color: #aaa; }
.field:focus { border-color: #999; }

.textarea { line-height: 1.5; }

.actions {
  display: flex;
  align-items: center;
  gap: 1.25rem;
  margin-top: 1.25rem;
}

.btn {
  padding: 0.75rem 1.5rem;
  background: #0a0a0a;
  color: #fff;
  border: none;
  font-family: 'Cousine', monospace;
  font-size: 0.9rem;
  cursor: pointer;
  transition: opacity 0.15s;
}

.btn:disabled { opacity: 0.4; cursor: default; }
.btn:not(:disabled):hover { opacity: 0.75; }

.ghost {
  background: none;
  border: none;
  color: #aaa;
  font-family: 'Cousine', monospace;
  font-size: 0.85rem;
  cursor: pointer;
  padding: 0;
  transition: color 0.15s;
}
.ghost:hover { color: #666; }

.msg {
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
  font-size: 0.85rem;
}

.error  { background: #fff0f0; border: 1px solid #f0b0b0; color: #a03030; }
.success { background: #f0fff0; border: 1px solid #b0e0b0; color: #307030; }

.footer {
  margin-top: 2rem;
  font-size: 0.75rem;
}

.faq-link {
  color: #aaa;
  text-decoration: none;
}
.faq-link:hover { color: #555; }
</style>
