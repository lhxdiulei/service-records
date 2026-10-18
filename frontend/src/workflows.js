/**
 * A failed step with the last successful state attached. Callers can keep the
 * imported batch or saved revision visible and retry only the remaining step.
 */
export class WorkflowError extends Error {
  constructor(cause, state) {
    super(cause instanceof Error ? cause.message : String(cause), { cause })
    this.name = 'WorkflowError'
    if (cause?.status !== undefined) this.status = cause.status
    if (cause?.code !== undefined) this.code = cause.code
    Object.assign(this, state)
  }
}

/**
 * Confirm an import before starting extraction. An already confirmed import
 * skips confirmation. start receives this call's confirmation response, if any.
 * Errors expose stage (confirm/extract), confirmed, and confirmation.
 */
export async function confirmThenExtract({ confirmed = false, confirm, start }) {
  let confirmation
  if (!confirmed) {
    try {
      confirmation = await confirm()
      confirmed = true
    } catch (cause) {
      throw new WorkflowError(cause, { stage: 'confirm', confirmed: false, confirmation })
    }
  }
  try {
    const job = await start(confirmation)
    return { confirmed: true, confirmation, job }
  } catch (cause) {
    throw new WorkflowError(cause, { stage: 'extract', confirmed: true, confirmation })
  }
}

function requireRevision(revision) {
  if (!revision || typeof revision.id !== 'string' || !revision.id.trim()) {
    const error = new Error('未取得明确的草稿版本，请刷新记录后再提交审核')
    error.code = 'missing_revision'
    throw error
  }
}

/**
 * Save only when needed, then submit that exact revision. save must return the
 * revision object (including id), not an unnormalised API response. Callers can
 * update their object/version state inside save before returning the revision.
 * Errors expose stage (save/submit), saved, and the known revision. A resolved
 * save counts as saved even if its response lacks a revision; do not blindly
 * create another version after an incomplete response.
 */
export async function saveThenSubmit({ needsSave, save, submit, revision }) {
  let saved = false
  if (needsSave) {
    try {
      revision = await save()
      saved = true
      requireRevision(revision)
    } catch (cause) {
      throw new WorkflowError(cause, { stage: 'save', saved, revision })
    }
  }
  try {
    requireRevision(revision)
    const submission = await submit(revision)
    return { revision, saved, submission }
  } catch (cause) {
    throw new WorkflowError(cause, { stage: 'submit', saved, revision })
  }
}
