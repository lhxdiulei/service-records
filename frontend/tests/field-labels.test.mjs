import test from 'node:test'
import assert from 'node:assert/strict'
import { fieldLabel, apiErrorMessage } from '../src/field-labels.js'

test('editor fields use the same business names as the visible form', () => {
  assert.equal(fieldLabel('problem'), '问题内容')
  assert.equal(fieldLabel('handling_summary'), '处理过程')
  assert.equal(fieldLabel('current_conclusion'), '当前结论')
  assert.equal(fieldLabel('question'), '问题')
  assert.equal(fieldLabel('answer'), '回答')
})

test('nested validation paths identify the visible fact and item without internal field names', () => {
  const result = apiErrorMessage([
    { loc: ['body', 'content', 'claims', 2, 'text'], type: 'string_too_short', ctx: { min_length: 1 } },
    { loc: ['body', 'content', 'current_conclusion'], type: 'string_too_long', ctx: { max_length: 20000 } },
  ], 422)
  assert.equal(result, '关键事实与依据 · 第 3 项 · 内容：至少填写 1 个字符；当前结论：最多填写 20000 个字符')
  assert.doesNotMatch(result, /body|content|claims|current_conclusion|string_too/)
})

test('business rule messages and error status fallback remain readable', () => {
  const message = '以下内容尚未关联支持它的原文依据：关键事实 1。请在“原文与依据”中补充。'
  assert.equal(apiErrorMessage({ code: 'evidence_missing', message }, 422), message)
  assert.equal(apiErrorMessage(undefined, 503), '请求失败 (503)')
})

test('required, selection and unknown validation errors do not expose implementation names or values', () => {
  assert.equal(apiErrorMessage([{ loc: ['body', 'content', 'first_question_message_id'], type: 'uuid_parsing' }], 422), '原始提问消息：请选择有效记录')
  assert.equal(apiErrorMessage([{ loc: ['body', 'content', 'answer'], type: 'missing' }], 422), '回答：请填写此项')
  assert.equal(apiErrorMessage([{ loc: ['body', 'internal_field'], type: 'unexpected', msg: 'database detail', input: 'private value' }], 422), '填写内容：格式不正确，请检查此项')
})
