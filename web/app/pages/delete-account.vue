<script setup lang="ts">
import { useFirebaseAuth, useCurrentUser } from 'vuefire'
import {
  EmailAuthProvider,
  reauthenticateWithCredential,
  deleteUser,
} from 'firebase/auth'

const auth = useFirebaseAuth()
const user = useCurrentUser()
const router = useRouter()

const DB = 'https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app'

// client-side keys to clear on deletion (not stored in the DB)
const LS_KEYS = [
  'discogsToken', 'discogsUser', 'showDebug',
  'diig_store_prefs', 'diig_last_store',
  'diig_dq_q', 'diig_dq_year', 'diig_dq_genres', 'diig_dq_styles', 'diig_dq_fmt',
]

const password  = ref('')
const confirmed = ref(false)
const loading   = ref(false)
const error     = ref('')

const canDelete = computed(() => !!user.value && password.value.length >= 6 && confirmed.value)

function getDeleteError(code: string) {
  return ({
    'auth/wrong-password': 'Incorrect password.',
    'auth/invalid-credential': 'Incorrect password.',
    'auth/too-many-requests': 'Too many attempts — try again later.',
    'auth/network-request-failed': 'Network error — check your connection and try again.',
    'auth/requires-recent-login': 'Please sign in again, then retry.',
  } as Record<string, string>)[code] ?? 'Something went wrong, please try again.'
}

async function handleDelete() {
  if (!auth || !user.value || !canDelete.value) return
  loading.value = true
  error.value = ''

  const u = user.value
  const uid = u.uid
  let dbCleared = false

  try {
    // 1. reauthenticate — deleteUser requires a recent login
    const cred = EmailAuthProvider.credential(u.email ?? '', password.value)
    await reauthenticateWithCredential(u, cred)

    // 2. fresh id token for the REST calls
    const token = await u.getIdToken()

    // 3. gather the user's like memberships (mirrored under the shared /likes node)
    const likesRes = await fetch(`${DB}/users/${uid}/likes.json?auth=${token}`)
    const likes = likesRes.ok ? await likesRes.json() : null

    // 4. atomic multi-path delete: the user blob + every like membership
    const payload: Record<string, null> = { [`users/${uid}`]: null }
    if (likes && typeof likes === 'object') {
      for (const rid of Object.keys(likes)) payload[`likes/${rid}/${uid}`] = null
    }
    const patchRes = await fetch(`${DB}/.json?auth=${token}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!patchRes.ok) throw new Error('db-delete-failed')
    dbCleared = true

    // 5. delete the firebase auth account
    await deleteUser(u)

    // 6. best-effort local cleanup
    for (const k of LS_KEYS) localStorage.removeItem(k)

    // 7. done
    await router.push('/login?deleted=1')
  } catch (err: any) {
    error.value = dbCleared
      ? 'Your data was removed, but finishing account deletion failed. Please try again.'
      : getDeleteError(err?.code)
    loading.value = false
  }
}
</script>

<template>
  <div class="page">
    <div class="card">
      <NuxtLink to="/" class="back">&#8592; back</NuxtLink>

      <h1 class="title">Delete account</h1>

      <p class="lead">
        This permanently deletes your diig account and all associated data. This cannot be undone.
      </p>

      <ul class="what">
        <li>Your account and email sign-in</li>
        <li>Your username and preferences</li>
        <li>Your likes</li>
      </ul>

      <div v-if="error" class="msg error">{{ error }}</div>

      <template v-if="user">
        <p class="signed-in">Signed in as <strong>{{ user.email }}</strong></p>

        <form @submit.prevent="handleDelete">
          <input
            v-model="password"
            type="password"
            placeholder="confirm your password"
            autocomplete="current-password"
            required
            class="field"
          />

          <label class="confirm">
            <input v-model="confirmed" type="checkbox" />
            <span>I understand this is permanent</span>
          </label>

          <div class="actions">
            <button type="submit" :disabled="loading || !canDelete" class="btn danger">
              {{ loading ? 'deleting...' : 'permanently delete my account' }}
            </button>
            <NuxtLink to="/" class="ghost">cancel</NuxtLink>
          </div>
        </form>
      </template>

      <p v-else class="lead">Loading…</p>
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
  padding: 3rem 1rem;
}

.card {
  width: 100%;
  max-width: 420px;
}

.back {
  display: inline-block;
  font-size: 0.75rem;
  color: #aaa;
  text-decoration: none;
  margin-bottom: 2rem;
}
.back:hover { color: #555; }

.title {
  font-size: 1.6rem;
  color: #0a0a0a;
  margin: 0 0 1rem;
  letter-spacing: 0.04em;
}

.lead {
  font-size: 0.85rem;
  color: #555;
  line-height: 1.7;
  margin: 0 0 1rem;
}

.what {
  margin: 0 0 1.5rem;
  padding-left: 1.2rem;
}
.what li {
  font-size: 0.85rem;
  color: #555;
  line-height: 1.7;
}

.signed-in {
  font-size: 0.8rem;
  color: #666;
  margin: 0 0 1rem;
}
.signed-in strong { color: #0a0a0a; }

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
}
.field::placeholder { color: #aaa; }
.field:focus { border-color: #999; }

.confirm {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8rem;
  color: #555;
  margin-bottom: 1.25rem;
  cursor: pointer;
}

.actions {
  display: flex;
  align-items: center;
  gap: 1.25rem;
}

.btn {
  padding: 0.75rem 1.5rem;
  border: none;
  font-family: 'Cousine', monospace;
  font-size: 0.9rem;
  cursor: pointer;
  transition: opacity 0.15s;
  color: #fff;
}
.btn.danger { background: #a03030; }
.btn:disabled { opacity: 0.4; cursor: default; }
.btn:not(:disabled):hover { opacity: 0.8; }

.ghost {
  color: #aaa;
  font-size: 0.85rem;
  text-decoration: none;
  transition: color 0.15s;
}
.ghost:hover { color: #666; }

.msg {
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
  font-size: 0.85rem;
}
.error { background: #fff0f0; border: 1px solid #f0b0b0; color: #a03030; }
</style>
