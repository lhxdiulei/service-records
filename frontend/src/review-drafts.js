import { computed, reactive } from 'vue'

// Keep unsubmitted comments separate by account, record and revision. These drafts
// stay in memory; browser close/reload is protected by the editor's unload guard.
export function useReviewDrafts(key) {
  const drafts = reactive(new Map())
  const comment = computed({
    get: () => drafts.get(key.value) || '',
    set: value => {
      if (!key.value) return
      if (value) drafts.set(key.value, value)
      else drafts.delete(key.value)
    },
  })
  return { comment, clear: () => { comment.value = '' }, reset: () => drafts.clear() }
}
