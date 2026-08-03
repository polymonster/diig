const PUBLIC_PATHS = ['/login', '/faq', '/privacy', '/terms']

export default defineNuxtRouteMiddleware(async (to) => {
  const currentUser = await getCurrentUser()

  if (!currentUser && !PUBLIC_PATHS.includes(to.path)) {
    // preserve the target so login can send the user back (e.g. /delete-account
    // opened from the native app)
    return navigateTo({ path: '/login', query: { redirect: to.fullPath } })
  }
})