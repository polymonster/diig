import { useCurrentUser } from 'vuefire'

// The signed in user's display name (/users/<uid>/username), shown in the
// menu and edited in settings

const username = ref('')   // as saved, '' when never set

export function useProfile() {
  const user = useCurrentUser()
  const db   = useDb()

  // the username, or the email for accounts that never set one
  const displayName = computed(() => username.value || user.value?.email || '')

  async function loadProfile() {
    if (!user.value) { username.value = ''; return }
    username.value = (await db.get<string>(`users/${user.value.uid}/username`)) || ''
  }

  async function saveUsername(name: string): Promise<boolean> {
    if (!user.value) return false
    const ok = await db.put(`users/${user.value.uid}/username`, name)
    if (ok) username.value = name
    return ok
  }

  return { username, displayName, loadProfile, saveUsername }
}
