import test from 'node:test'
import assert from 'node:assert/strict'
import { confirmThenExtract, saveThenSubmit, WorkflowError } from '../src/workflows.js'

function deferred() {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

function apiError(message, status, code) {
  return Object.assign(new Error(message), { status, code })
}

test('extraction waits for successful import confirmation and receives its result', async () => {
  const confirmation = deferred()
  const calls = []
  const batch = { id: 'batch-1', confirmed_at: '2026-10-16' }
  const job = { id: 'job-1' }
  const pending = confirmThenExtract({
    confirm: () => { calls.push('confirm'); return confirmation.promise },
    start: result => { calls.push('extract'); assert.equal(result, batch); return job },
  })
  assert.deepEqual(calls, ['confirm'])
  confirmation.resolve(batch)
  assert.deepEqual(await pending, { confirmed: true, confirmation: batch, job })
  assert.deepEqual(calls, ['confirm', 'extract'])
})

test('failed confirmation never starts extraction and retains the API error', async () => {
  const cause = apiError('请确认解析警告', 409, 'parse_warnings_unaccepted')
  await assert.rejects(confirmThenExtract({
    confirm: async () => { throw cause },
    start: () => assert.fail('must not extract unconfirmed messages'),
  }), error => {
    assert.ok(error instanceof WorkflowError)
    assert.equal(error.cause, cause)
    assert.equal(error.message, cause.message)
    assert.equal(error.status, 409)
    assert.equal(error.code, cause.code)
    assert.equal(error.stage, 'confirm')
    assert.equal(error.confirmed, false)
    return true
  })
})

test('failed extraction keeps confirmed import state so retry does not confirm again', async () => {
  const batch = { id: 'batch-1', version: 2 }
  let confirmations = 0
  let failure
  try {
    await confirmThenExtract({
      confirm: async () => { confirmations++; return batch },
      start: async () => { throw apiError('模型暂不可用', 503, 'model_unavailable') },
    })
    assert.fail('expected extraction failure')
  } catch (error) { failure = error }
  assert.equal(failure.stage, 'extract')
  assert.equal(failure.confirmed, true)
  assert.equal(failure.confirmation, batch)
  assert.equal(failure.status, 503)
  assert.equal(failure.code, 'model_unavailable')
  const retried = await confirmThenExtract({
    confirmed: failure.confirmed,
    confirm: () => { confirmations++; assert.fail('already imported') },
    start: async () => ({ id: 'job-1' }),
  })
  assert.equal(confirmations, 1)
  assert.equal(retried.job.id, 'job-1')
})

test('already imported batch can start extraction without a confirm callback', async () => {
  const result = await confirmThenExtract({ confirmed: true, start: async () => ({ id: 'job-2' }) })
  assert.equal(result.confirmed, true)
  assert.equal(result.confirmation, undefined)
  assert.equal(result.job.id, 'job-2')
})

test('submit waits for save and uses its exact revision instead of the previous revision', async () => {
  const save = deferred()
  const previous = Object.freeze({ id: 'old', state_version: 2 })
  const saved = Object.freeze({ id: 'new', state_version: 1 })
  const calls = []
  const pending = saveThenSubmit({
    needsSave: true,
    revision: previous,
    save: () => { calls.push('save'); return save.promise },
    submit: revision => {
      calls.push('submit')
      assert.equal(revision, saved)
      return { state: 'in_review' }
    },
  })
  assert.deepEqual(calls, ['save'])
  save.resolve(saved)
  assert.deepEqual(await pending, { revision: saved, saved: true, submission: { state: 'in_review' } })
  assert.deepEqual(calls, ['save', 'submit'])
})

test('save conflict prevents submission and preserves the old revision and error details', async () => {
  const previous = { id: 'old' }
  const cause = apiError('记录已更新', 409, 'version_conflict')
  await assert.rejects(saveThenSubmit({
    needsSave: true,
    revision: previous,
    save: async () => { throw cause },
    submit: () => assert.fail('must not submit after failed save'),
  }), error => {
    assert.equal(error.stage, 'save')
    assert.equal(error.saved, false)
    assert.equal(error.revision, previous)
    assert.equal(error.cause, cause)
    assert.equal(error.message, cause.message)
    assert.equal(error.status, 409)
    assert.equal(error.code, cause.code)
    return true
  })
})

test('validation rejection preserves the saved draft and retry submits without another save', async () => {
  const revision = { id: 'saved-draft', state_version: 1 }
  const cause = apiError('关键事实缺少证据', 422, 'missing_evidence')
  let saveCount = 0
  let failure
  try {
    await saveThenSubmit({
      needsSave: true,
      revision: { id: 'old-draft' },
      save: async () => { saveCount++; return revision },
      submit: async current => { assert.equal(current, revision); throw cause },
    })
    assert.fail('expected submit rejection')
  } catch (error) { failure = error }
  assert.equal(failure.stage, 'submit')
  assert.equal(failure.saved, true)
  assert.equal(failure.revision, revision)
  assert.equal(failure.cause, cause)
  assert.equal(failure.message, cause.message)
  assert.equal(failure.status, 422)
  assert.equal(failure.code, cause.code)
  const retry = await saveThenSubmit({
    needsSave: false,
    revision: failure.revision,
    save: () => { saveCount++; assert.fail('saved draft should not be duplicated') },
    submit: async current => { assert.equal(current, revision); return { state: 'in_review' } },
  })
  assert.equal(saveCount, 1)
  assert.equal(retry.saved, false)
  assert.equal(retry.submission.state, 'in_review')
})

test('unchanged draft is submitted directly, without a save callback', async () => {
  const revision = { id: 'unchanged-draft', state_version: 3 }
  const result = await saveThenSubmit({
    needsSave: false,
    revision,
    submit: async current => { assert.equal(current, revision); return { state: 'in_review' } },
  })
  assert.equal(result.saved, false)
  assert.equal(result.revision, revision)
})

test('missing revision from successful save is never replaced with the old revision', async () => {
  await assert.rejects(saveThenSubmit({
    needsSave: true,
    revision: { id: 'old' },
    save: async () => undefined,
    submit: () => assert.fail('must not guess which revision was saved'),
  }), error => {
    assert.equal(error.stage, 'save')
    assert.equal(error.saved, true)
    assert.equal(error.revision, undefined)
    assert.equal(error.code, 'missing_revision')
    return true
  })
})

test('direct submit with no revision fails before calling the API', async () => {
  await assert.rejects(saveThenSubmit({
    needsSave: false,
    submit: () => assert.fail('must not submit without a revision'),
  }), error => {
    assert.equal(error.stage, 'submit')
    assert.equal(error.saved, false)
    assert.equal(error.code, 'missing_revision')
    return true
  })
})
