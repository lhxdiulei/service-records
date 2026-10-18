import test from 'node:test'
import assert from 'node:assert/strict'
import { earliestVisibleMessage, excerptOccurrences, selectionEvidence, contributorCandidates } from '../src/editor-assist.js'

test('first visible message ignores deleted and unknown dates without sorting the input', () => {
  const messages = [
    { id: 'later', sent_at: '2026-10-16T08:00:00+08:00' },
    { id: 'deleted', sent_at: '2026-10-14T08:00:00+08:00', is_deleted: true },
    { id: 'invalid', sent_at: 'unknown' },
    { id: 'unknown', sent_at: null },
    { id: 'earliest', sent_at: '2026-10-15T08:00:00+08:00' },
    { id: 'same-time', sent_at: '2026-10-15T00:00:00Z' },
  ]
  const snapshot = structuredClone(messages)
  assert.equal(earliestVisibleMessage(messages), messages[4])
  assert.deepEqual(messages, snapshot)
})

test('no valid timestamp has no inferred first visible message', () => {
  assert.equal(earliestVisibleMessage(), null)
  assert.equal(earliestVisibleMessage([{ sent_at: null }, { sent_at: '' }, { sent_at: ' ' }, { sent_at: 0 }, { sent_at: 'invalid' }]), null)
  assert.equal(earliestVisibleMessage([{ sent_at: '2026-10-15T00:00:00Z', is_deleted: true }]), null)
})

test('overlapping occurrences match Python find(start + 1)', () => {
  assert.deepEqual(excerptOccurrences('aaaa', 'aa'), [
    { occurrence: 1, start_cp: 0, end_cp: 2, start_utf16: 0, end_utf16: 2 },
    { occurrence: 2, start_cp: 1, end_cp: 3, start_utf16: 1, end_utf16: 3 },
    { occurrence: 3, start_cp: 2, end_cp: 4, start_utf16: 2, end_utf16: 4 },
  ])
  assert.deepEqual(selectionEvidence('aaaa', 1, 3), { exact_excerpt: 'aa', occurrence: 2, start_cp: 1, end_cp: 3 })
})

test('emoji repetition reports separate code-point and browser offsets', () => {
  assert.deepEqual(excerptOccurrences('😀😀😀', '😀😀'), [
    { occurrence: 1, start_cp: 0, end_cp: 2, start_utf16: 0, end_utf16: 4 },
    { occurrence: 2, start_cp: 1, end_cp: 3, start_utf16: 2, end_utf16: 6 },
  ])
  assert.deepEqual(selectionEvidence('😀😀😀', 2, 6), { exact_excerpt: '😀😀', occurrence: 2, start_cp: 1, end_cp: 3 })
})

test('selection preserves combining marks, CRLF and exact whitespace', () => {
  const raw = '😀e\u0301\r\n e\u0301\r\n'
  assert.deepEqual(selectionEvidence(raw, 7, 11), { exact_excerpt: 'e\u0301\r\n', occurrence: 2, start_cp: 6, end_cp: 10 })
  assert.deepEqual(selectionEvidence(' x ', 0, 3), { exact_excerpt: ' x ', occurrence: 1, start_cp: 0, end_cp: 3 })
  assert.deepEqual(excerptOccurrences(raw, 'é'), [])
  assert.deepEqual(selectionEvidence('e\u0301', 1, 2), { exact_excerpt: '\u0301', occurrence: 1, start_cp: 1, end_cp: 2 })
})

test('invalid ranges and half-surrogate selections are rejected', () => {
  for (const [start, end] of [[-1, 1], [0, 4], [1, 1], [2, 1], [0.5, 2], [0, NaN], [0, 1], [1, 2]]) {
    assert.equal(selectionEvidence('😀x', start, end), null, `${start}, ${end}`)
  }
  assert.equal(selectionEvidence(null, 0, 1), null)
  assert.deepEqual(excerptOccurrences('😀', '\ud83d'), [])
  assert.deepEqual(excerptOccurrences('😀', '\ude00'), [])
  assert.deepEqual(excerptOccurrences('abc', ''), [])
  assert.deepEqual(excerptOccurrences('abc', 'missing'), [])
})

const participants = [{ id: 'alice', display_name: '小王' }, { id: 'bob', display_name: '小李' }]
function source(id, author, raw, spans = [{ start_cp: 0, end_cp: Array.from(raw).length }]) {
  return { id, sender_participant_id: author, raw_text: raw, direct_body_spans: spans }
}
function evidence(id, message, start, end, field = 'answer', relation = 'supports') {
  return { evidence_span_id: id, message_id: message.id, start_cp: start, end_cp: end, field_key: field, relation, excerpt: Array.from(message.raw_text).slice(start, end).join('') }
}

test('only the exact direct-body occurrence recommends the message author', () => {
  const message = source('message', 'alice', '> 请重启😀\r\n请重启😀', [{ start_cp: 8, end_cp: 12 }])
  const quoted = evidence('quote', message, 2, 6)
  const direct = evidence('direct', message, 8, 12)
  assert.deepEqual(contributorCandidates([quoted], [message], participants), [])
  assert.deepEqual(contributorCandidates([quoted, direct], [message], participants), [{
    participant_id: 'alice', display_name: '小王', contribution: '提供关键解答',
    evidence_span_ids: ['direct'], message_ids: ['message'], excerpts: ['请重启😀'],
  }])
})

test('candidates aggregate direct answer evidence by author and deduplicate bindings', () => {
  const first = source('first', 'alice', '请重启')
  const followup = source('followup', 'alice', '检查网络')
  const another = source('another', 'bob', '检查权限')
  const bindings = [
    evidence('one', first, 0, 3), evidence('one', first, 0, 3, 'answer_claims.c1'),
    evidence('two', followup, 0, 4, 'answer_claims.c2'), evidence('three', another, 0, 4),
  ]
  const messages = [first, followup, another]
  const snapshot = structuredClone({ bindings, messages, participants })
  assert.deepEqual(contributorCandidates(bindings, messages, participants), [
    { participant_id: 'alice', display_name: '小王', contribution: '提供关键解答', evidence_span_ids: ['one', 'two'], message_ids: ['first', 'followup'], excerpts: ['请重启', '检查网络'] },
    { participant_id: 'bob', display_name: '小李', contribution: '提供关键解答', evidence_span_ids: ['three'], message_ids: ['another'], excerpts: ['检查权限'] },
  ])
  assert.deepEqual({ bindings, messages, participants }, snapshot)
})

test('questions, context, contradictions and empty answer claim keys are not contribution evidence', () => {
  const message = source('message', 'alice', '请重启')
  const bindings = [
    evidence('question', message, 0, 3, 'question'), evidence('ticket', message, 0, 3, 'claims.c1'),
    evidence('empty', message, 0, 3, 'answer_claims.'), evidence('context', message, 0, 3, 'answer', 'context'),
    evidence('contradicts', message, 0, 3, 'answer_claims.c1', 'contradicts'),
  ]
  assert.deepEqual(contributorCandidates(bindings, [message], participants), [])
})

test('deleted, missing and unknown authors or body boundaries never produce a recommendation', () => {
  const messages = [
    { ...source('deleted', 'alice', '请重启'), is_deleted: true },
    source('unknown-author', null, '请重启'), source('missing-author', 'charlie', '请重启'),
    source('unknown-body', 'alice', '请重启', []), source('missing-body', 'alice', '请重启', null),
  ]
  const bindings = messages.map(message => evidence(message.id, message, 0, 3))
  bindings.push({ ...bindings[0], message_id: 'missing-message' })
  assert.deepEqual(contributorCandidates(bindings, messages, participants), [])
})

test('out-of-range, stale, empty and cross-span evidence is excluded', () => {
  const message = source('message', 'alice', '甲乙\r\n丙丁', [{ start_cp: 0, end_cp: 4 }, { start_cp: 4, end_cp: 6 }])
  const bindings = [
    evidence('cross-span', message, 0, 6), evidence('empty', message, 1, 1),
    evidence('negative', message, -1, 2), evidence('past-end', message, 0, 99),
    { ...evidence('stale', message, 0, 2), excerpt: '另一句' },
    { ...evidence('fraction', message, 0, 2), start_cp: 0.5 },
    { ...evidence('missing-id', message, 0, 2), evidence_span_id: null },
  ]
  assert.deepEqual(contributorCandidates(bindings, [message], participants), [])
})
