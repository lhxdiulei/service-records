import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

// UI-only overlay state. Business navigation and unsaved-edit checks stay in App.
export function useMobileShell({ preview, deletion, jobResults, loading }) {
  const isMobile = ref(false)
  const mobileNavOpen = ref(false)
  const navToggle = ref(null)
  const navPanel = ref(null)
  const navClose = ref(null)
  const appDialog = computed(() => preview.value ? 'preview' : jobResults.value ? 'results' : deletion.value ? 'delete' : '')
  const backgroundBlocked = computed(() => !!appDialog.value || (isMobile.value && mobileNavOpen.value))
  let media, previousOverflow, dialogTrigger
  function rememberDialogTrigger(event) {
    // Capture before an async action disables its button and the browser drops focus.
    if (!appDialog.value) {
      const trigger = event.target.closest?.('button, summary, a')
      if (trigger) dialogTrigger = trigger
    }
  }
  const focusable = root => [...(root?.querySelectorAll('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex="0"]') || [])]
    .filter(element => !element.closest('[inert]') && element.getClientRects().length)

  async function closeMobileNav(restoreFocus = true) {
    mobileNavOpen.value = false
    await nextTick()
    if (restoreFocus && isMobile.value) navToggle.value?.focus({ preventScroll: true })
  }
  async function toggleMobileNav() {
    if (mobileNavOpen.value) return closeMobileNav()
    mobileNavOpen.value = true
    await nextTick()
    // Let the newly visible drawer enter layout before moving keyboard focus.
    requestAnimationFrame(() => {
      if (mobileNavOpen.value) navClose.value?.focus({ preventScroll: true })
    })
  }
  function closeAppDialog() {
    if (loading.value) return
    if (preview.value) preview.value = null
    else if (jobResults.value) jobResults.value = null
    else deletion.value = null
  }
  function trapOverlayKeys(event, root, close) {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); return }
    if (event.key !== 'Tab') return
    const elements = focusable(root)
    if (!elements.length) { event.preventDefault(); root?.focus(); return }
    const first = elements[0], last = elements.at(-1)
    if (event.shiftKey && (document.activeElement === first || !root.contains(document.activeElement))) {
      event.preventDefault(); last.focus()
    } else if (!event.shiftKey && (document.activeElement === last || !root.contains(document.activeElement))) {
      event.preventDefault(); first.focus()
    }
  }
  function navKeydown(event) {
    if (isMobile.value && mobileNavOpen.value) trapOverlayKeys(event, navPanel.value, closeMobileNav)
  }
  function dialogKeydown(event) { trapOverlayKeys(event, event.currentTarget.querySelector('[role="dialog"]'), closeAppDialog) }
  watch(backgroundBlocked, blocked => {
    if (blocked && previousOverflow === undefined) {
      previousOverflow = document.body.style.overflow
      document.body.style.overflow = 'hidden'
    } else if (!blocked && previousOverflow !== undefined) {
      document.body.style.overflow = previousOverflow
      previousOverflow = undefined
    }
  })
  watch(appDialog, async (current, previous) => {
    if (current && !previous && !dialogTrigger?.isConnected) dialogTrigger = document.activeElement
    // A delayed response may open a dialog after the user has opened navigation.
    // Keep only one overlay active so the dialog cannot be covered by an inert drawer.
    if (current) mobileNavOpen.value = false
    await nextTick()
    if (current) {
      const dialog = document.querySelector(`[data-app-dialog="${current}"]`)
      ;(focusable(dialog)[0] || dialog)?.focus()
    } else if (dialogTrigger?.isConnected) {
      const target = dialogTrigger.getClientRects().length ? dialogTrigger : dialogTrigger.closest('details')?.querySelector('summary')
      if (target?.getClientRects().length && !target.closest('[inert]')) target.focus({ preventScroll: true })
      else navToggle.value?.focus({ preventScroll: true })
    }
    else navToggle.value?.focus()
  })
  function resize() {
    isMobile.value = media.matches
    if (!media.matches) mobileNavOpen.value = false
  }
  onMounted(() => {
    media = window.matchMedia('(max-width: 780px)')
    resize()
    media.addEventListener('change', resize)
  })
  onUnmounted(() => {
    media?.removeEventListener('change', resize)
    if (previousOverflow !== undefined) document.body.style.overflow = previousOverflow
  })
  return { isMobile, mobileNavOpen, navToggle, navPanel, navClose, appDialog, backgroundBlocked, toggleMobileNav, closeMobileNav, navKeydown, closeAppDialog, dialogKeydown, rememberDialogTrigger }
}
