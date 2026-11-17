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
const route = useRoute()

// shown after an account has been deleted (redirected here from /delete-account)
const deleted = computed(() => route.query.deleted != null)

// ── Tabs ─────────────────────────────────────────────────────────────────────
// /login?invite=K7QX-M2PA opens the sign up tab with the code filled in
type Tab = 'login' | 'signup' | 'register'
const queryInvite = typeof route.query.invite === 'string' ? route.query.invite : ''
const tab = ref<Tab>('invite' in route.query ? 'signup' : 'login')

// ── Login ─────────────────────────────────────────────────────────────────────
const email = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const success = ref('')
const showForgotPassword = ref(false)
const resetLoading = ref(false)

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

const isValidEmail = computed(() => EMAIL_RE.test(email.value))
const isFormValid = computed(() => isValidEmail.value && password.value.length >= 6)

// after a fresh sign up we stay here to show the welcome / testflight panel
const signedUp = ref(false)

function continueToApp() {
  const redirect = route.query.redirect
  router.push(typeof redirect === 'string' ? redirect : '/')
}

watch(user, (newUser) => {
  if (newUser && !signedUp.value) {
    continueToApp()
  }
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

// ── Sign up (invite only) ─────────────────────────────────────────────────────
// accounts are created by the signup cloud function (functions/index.js), which
// claims a use of the invite code. errors come back in identitytoolkit shape.
const testflightUrl = useRuntimeConfig().public.testflightUrl as string

const suEmail = ref('')
const suPassword = ref('')
const suInvite = ref(queryInvite)
const suLoading = ref(false)

const normalisedInvite = computed(() => suInvite.value.toUpperCase().replace(/[^A-Z0-9]/g, ''))
const isSignupValid = computed(() =>
  EMAIL_RE.test(suEmail.value) && suPassword.value.length >= 6 && normalisedInvite.value.length >= 6
)

const getSignupErrorMessage = (code: string) => ({
  INVALID_INVITE_CODE: 'That invite code isn\'t valid.',
  INVITE_CODE_USED: 'That invite code has already been used.',
  INVITE_CODE_EXPIRED: 'That invite code has expired.',
  EMAIL_EXISTS: 'An account with that email already exists — try signing in.',
  INVALID_EMAIL: 'Invalid email address.',
  MISSING_EMAIL_OR_PASSWORD: 'Enter an email and password.',
  TOO_MANY_ATTEMPTS_TRY_LATER: 'Too many attempts — try again later.',
} as Record<string, string>)[code.split(' ')[0] ?? ''] ?? (code.startsWith('WEAK_PASSWORD')
  ? 'Password should be at least 6 characters.'
  : 'Something went wrong, please try again.')

const handleSignup = async () => {
  if (!auth || !isSignupValid.value) return
  suLoading.value = true
  error.value = ''
  try {
    const res = await fetch('/api/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: suEmail.value, password: suPassword.value, invite: suInvite.value }),
    })
    // only trust the function's own {ok: true}. if /api/signup isn't routed to
    // the function (old hosting deploy, nuxt dev) the spa fallback answers 200
    // with index.html, which must not be mistaken for a created account.
    const data = await res.json().catch(() => null) as { ok?: boolean, error?: { message?: string } } | null
    if (!data) {
      error.value = 'Sign up is unavailable right now, please try again later.'
      return
    }
    if (!res.ok || data.ok !== true) {
      error.value = getSignupErrorMessage(data.error?.message ?? '')
      return
    }
    signedUp.value = true
    await setPersistence(auth, browserLocalPersistence)
    await signInWithEmailAndPassword(auth, suEmail.value, suPassword.value)
  } catch {
    // account was created but sign in failed, send them to the sign in tab
    if (signedUp.value) {
      signedUp.value = false
      email.value = suEmail.value
      switchTab('login')
      success.value = 'Account created — please sign in.'
    } else {
      error.value = 'Something went wrong, please try again.'
    }
  } finally {
    suPassword.value = ''
    suLoading.value = false
  }
}

// ── Register interest ─────────────────────────────────────────────────────────
const regEmail = ref('')
const regMessage = ref('')
const regLoading = ref(false)
const regDone = ref(false)

const isRegEmailValid = computed(() => EMAIL_RE.test(regEmail.value))

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
  <div class="card-page">
    <div class="card">
      <h1 class="title">diig</h1>

      <!-- ── Welcome, after sign up ── -->
      <template v-if="signedUp && user">
        <div class="msg success">You're in — welcome to diig.</div>
        <p v-if="testflightUrl" class="blurb">
          On iPhone? Join the iOS beta on TestFlight to get the app.
        </p>
        <div class="actions">
          <a v-if="testflightUrl" :href="testflightUrl" target="_blank" rel="noopener" class="btn">get the iOS beta</a>
          <button type="button" :class="testflightUrl ? 'ghost' : 'btn'" @click="continueToApp">
            {{ testflightUrl ? 'continue on the web' : 'continue' }}
          </button>
        </div>
      </template>

      <template v-else>
      <div class="tabs">
        <button :class="['tab', { active: tab === 'login' }]" @click="switchTab('login')">sign in</button>
        <button :class="['tab', { active: tab === 'signup' }]" @click="switchTab('signup')">sign up</button>
        <button :class="['tab', { active: tab === 'register' }]" @click="switchTab('register')">register interest</button>
      </div>

      <div v-if="deleted" class="msg success">Your account has been deleted.</div>
      <div v-if="error" class="msg error">{{ error }}</div>
      <div v-if="success" class="msg success">{{ success }}</div>

      <!-- ── Sign up ── -->
      <template v-if="tab === 'signup'">
        <form @submit.prevent="handleSignup">
          <input v-model="suInvite" type="text" placeholder="invite code" autocomplete="off" autocapitalize="characters" spellcheck="false" required class="field">
          <input v-model="suEmail" type="email" placeholder="email" autocomplete="email" required class="field">
          <input v-model="suPassword" type="password" placeholder="password (6+ characters)" autocomplete="new-password" required class="field">
          <div class="actions">
            <button type="submit" :disabled="suLoading || !isSignupValid" class="btn">
              {{ suLoading ? 'creating account...' : 'sign up' }}
            </button>
            <button type="button" class="ghost" @click="switchTab('register')">no invite?</button>
          </div>
        </form>
      </template>

      <!-- ── Sign in ── -->
      <template v-else-if="tab === 'login'">
        <form v-if="!showForgotPassword" @submit.prevent="handleEmailLogin">
          <input v-model="email" type="email" placeholder="email" autocomplete="email" required class="field">
          <input v-model="password" type="password" placeholder="password" autocomplete="current-password" required class="field">
          <div class="actions">
            <button type="submit" :disabled="loading || !isFormValid" class="btn">
              {{ loading ? 'signing in...' : 'sign in' }}
            </button>
            <button type="button" class="ghost" @click="showForgotPassword = true">forgot password</button>
          </div>
        </form>

        <form v-else @submit.prevent="handlePasswordReset">
          <input v-model="email" type="email" placeholder="email" autocomplete="email" required class="field">
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
          <input v-model="regEmail" type="email" placeholder="email" autocomplete="email" required class="field">
          <textarea
            v-model="regMessage"
            placeholder="message"
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
      </template>

      <div class="footer">
        <NuxtLink to="/faq" class="footer-link">FAQ</NuxtLink>
        <span class="footer-sep">&middot;</span>
        <NuxtLink to="/privacy" class="footer-link">Privacy</NuxtLink>
        <span class="footer-sep">&middot;</span>
        <NuxtLink to="/terms" class="footer-link">Terms</NuxtLink>
      </div>
    </div>
  </div>
</template>

<style scoped>
.card { max-width: 400px; }

.title {
  font-size: 2rem;
  color: var(--ink);
  margin: 0 0 1.5rem;
  letter-spacing: 0.05em;
}

.tabs {
  display: flex;
  margin-bottom: 1.75rem;
  border-bottom: 1px solid var(--line);
}

.tab {
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  padding: 0.4rem 0;
  margin-right: 1.5rem;
  font-size: 0.8rem;
  color: #aaa;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}
.tab.active { color: var(--ink); border-bottom-color: var(--ink); }
.tab:not(.active):hover { color: #666; }

.textarea { line-height: 1.5; }

.blurb {
  font-size: 0.85rem;
  color: #666;
  margin: 1rem 0;
}

a.btn {
  display: inline-block;
  text-decoration: none;
}

.footer {
  margin-top: 2rem;
  font-size: 0.75rem;
}

.footer-link {
  color: #aaa;
  text-decoration: none;
}
.footer-link:hover { color: #555; }

.footer-sep {
  color: #ddd;
  margin: 0 0.4rem;
}
</style>
