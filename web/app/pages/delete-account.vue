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
const db     = useDb()

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

    // 2. gather the user's like memberships (mirrored under the shared /likes node)
    const likes = await db.get(`users/${uid}/likes`)

    // 3. atomic multi-path delete: the user blob + every like membership
    const payload: Record<string, null> = { [`users/${uid}`]: null }
    if (likes && typeof likes === 'object') {
      for (const rid of Object.keys(likes)) payload[`likes/${rid}/${uid}`] = null
    }
    if (!await db.patch('', payload)) throw new Error('db-delete-failed')
    dbCleared = true

    // 4. delete the firebase auth account
    await deleteUser(u)

    // 5. best-effort local cleanup
    storageClearAll()

    // 6. done
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
  <div class="card-page">
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
          >

          <label class="confirm">
            <input v-model="confirmed" type="checkbox">
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
.title {
  font-size: 1.6rem;
  color: var(--ink);
  margin: 0 0 1rem;
  letter-spacing: 0.04em;
}

.lead,
.what li {
  font-size: 0.85rem;
  color: #555;
  line-height: 1.7;
}
.lead { margin: 0 0 1rem; }

.what {
  margin: 0 0 1.5rem;
  padding-left: 1.2rem;
}

.signed-in {
  font-size: 0.8rem;
  color: #666;
  margin: 0 0 1rem;
}
.signed-in strong { color: var(--ink); }

.confirm {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8rem;
  color: #555;
  margin-bottom: 1.25rem;
  cursor: pointer;
}

.actions { margin-top: 0; }
</style>
