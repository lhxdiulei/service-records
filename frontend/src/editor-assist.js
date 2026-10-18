/** Helpers for editor suggestions. They never change source data or persist edits. */

export function earliestVisibleMessage(messages = []) {
  let earliest = null
  let earliestTime = Infinity
  for (const message of messages) {
    if (!message || message.is_deleted || typeof message.sent_at !== 'string' || !message.sent_at.trim()) continue
    const time = Date.parse(message.sent_at)
    if (Number.isFinite(time) && time < earliestTime) {
      earliest = message
      earliestTime = time
    }
  }
  return earliest
}

// Browser selections use UTF-16 offsets. The API and Python use code points.
// Only actual code point boundaries are entered, so half a surrogate pair is
// never accepted as the start or end of a citation.
function codePointBoundaries(raw) {
  const boundaries = new Map([[0, 0]])
  let utf16 = 0
  let codePoints = 0
  for (const character of raw) {
    utf16 += character.length
    boundaries.set(utf16, ++codePoints)
  }
  return boundaries
}

export function excerptOccurrences(raw, excerpt) {
  if (typeof raw !== 'string' || typeof excerpt !== 'string' || !excerpt.length) return []
  const boundaries = codePointBoundaries(raw)
  const occurrences = []
  let searchFrom = 0
  while (searchFrom <= raw.length) {
    const start = raw.indexOf(excerpt, searchFrom)
    if (start < 0) break
    const end = start + excerpt.length
    if (boundaries.has(start) && boundaries.has(end)) {
      occurrences.push({
        occurrence: occurrences.length + 1,
        start_cp: boundaries.get(start),
        end_cp: boundaries.get(end),
        start_utf16: start,
        end_utf16: end,
      })
    }
    // Deliberately include overlapping matches, as Python raw.find(start + 1)
    // does. Boundary checks above reject matches inside a surrogate pair.
    searchFrom = start + 1
  }
  return occurrences
}

export function selectionEvidence(raw, startUtf16, endUtf16) {
  if (typeof raw !== 'string' || !Number.isInteger(startUtf16) || !Number.isInteger(endUtf16)
    || startUtf16 < 0 || endUtf16 > raw.length || startUtf16 >= endUtf16) return null
  const boundaries = codePointBoundaries(raw)
  if (!boundaries.has(startUtf16) || !boundaries.has(endUtf16)) return null
  const exactExcerpt = raw.slice(startUtf16, endUtf16)
  const match = excerptOccurrences(raw, exactExcerpt).find(item => item.start_utf16 === startUtf16)
  if (!match) return null
  return { exact_excerpt: exactExcerpt, occurrence: match.occurrence, start_cp: match.start_cp, end_cp: match.end_cp }
}

export function contributorCandidates(bindings = [], messages = [], participants = []) {
  const messageById = new Map(messages.filter(Boolean).map(message => [message.id, message]))
  const participantById = new Map(participants.filter(Boolean).map(participant => [participant.id, participant]))
  const candidates = new Map()
  for (const binding of bindings) {
    if (!binding || binding.relation !== 'supports'
      || !(binding.field_key === 'answer' || /^answer_claims\..+$/.test(binding.field_key || ''))
      || typeof binding.evidence_span_id !== 'string' || !binding.evidence_span_id) continue
    const message = messageById.get(binding.message_id)
    if (!message || message.is_deleted || typeof message.raw_text !== 'string' || !message.sender_participant_id) continue
    const participant = participantById.get(message.sender_participant_id)
    if (!participant || participant.is_deleted) continue
    const { start_cp: start, end_cp: end } = binding
    const codePoints = Array.from(message.raw_text)
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > codePoints.length) continue
    // Use the stored position, never a text search: the same words may occur in
    // both a quotation and the sender's own reply. Match the backend's rule that
    // a contribution must fit entirely inside one known direct-body span.
    if (!Array.isArray(message.direct_body_spans) || !message.direct_body_spans.some(span => span
      && Number.isInteger(span.start_cp) && Number.isInteger(span.end_cp)
      && span.start_cp >= 0 && span.end_cp <= codePoints.length
      && span.start_cp <= start && end <= span.end_cp)) continue
    const excerpt = codePoints.slice(start, end).join('')
    if (binding.excerpt !== undefined && binding.excerpt !== excerpt) continue
    if (!candidates.has(participant.id)) {
      candidates.set(participant.id, {
        participant_id: participant.id,
        display_name: participant.display_name || message.sender_name_raw || '未命名成员',
        contribution: '提供关键解答',
        evidence_span_ids: [],
        message_ids: [],
        excerpts: [],
      })
    }
    const candidate = candidates.get(participant.id)
    if (!candidate.evidence_span_ids.includes(binding.evidence_span_id)) candidate.evidence_span_ids.push(binding.evidence_span_id)
    if (!candidate.message_ids.includes(message.id)) candidate.message_ids.push(message.id)
    if (!candidate.excerpts.includes(excerpt)) candidate.excerpts.push(excerpt)
  }
  return [...candidates.values()]
}
