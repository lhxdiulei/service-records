import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile, writeFile, unlink } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive } from 'vue'

// Exercise component events without a browser or any backend/model request.
const componentURL = new URL('../src/components/ContributorPicker.vue', import.meta.url)
const { descriptor } = parse(await readFile(componentURL, 'utf8'))
let compiled = compileScript(descriptor, { id: 'contributor-picker-test', inlineTemplate: true }).content
compiled = compiled.replace("import SearchSelect from './SearchSelect.vue'", "const SearchSelect = { name: 'SearchSelect', render() { return null } }")
  .replace("from '../editor-assist.js'", "from '../src/editor-assist.js'")
  .replace("import '../contributor-picker.css'", '')
const compiledURL = new URL(`.contributor-picker-${process.pid}.mjs`, import.meta.url)
let Component
try {
  await writeFile(compiledURL, compiled)
  Component = (await import(compiledURL.href)).default
} finally {
  await unlink(compiledURL).catch(() => {})
}

globalThis.document ??= { activeElement: null }
const renderer = createRenderer({
  createElement: type => ({ type, tagName: type.toUpperCase(), children: [], props: {}, text: '', listeners: {}, addEventListener(name, listener) { this.listeners[name] = listener } }),
  createText: text => ({ type: '#text', text }),
  createComment: text => ({ type: '#comment', text }),
  insert(node, parent, anchor = null) {
    if (node.parent) {
      const previous = node.parent.children.indexOf(node)
      if (previous >= 0) node.parent.children.splice(previous, 1)
    }
    node.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index >= 0) parent.children.splice(index, 0, node)
    else parent.children.push(node)
  },
  remove(node) { const index = node.parent?.children.indexOf(node); if (index >= 0) node.parent.children.splice(index, 1) },
  setText(node, text) { node.text = text },
  setElementText(node, text) { node.text = text; node.children = [] },
  patchProp(node, key, previous, next) { node.props[key] = next },
  parentNode: node => node.parent,
  nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1],
})

const participants = [{ id: 'one', display_name: '小王' }, { id: 'two', display_name: '小李' }]
const messages = [
  { id: 'message-one', sender_participant_id: 'one', raw_text: '请重启', direct_body_spans: [{ start_cp: 0, end_cp: 3 }] },
  { id: 'message-two', sender_participant_id: 'two', raw_text: '检查网络', direct_body_spans: [{ start_cp: 0, end_cp: 4 }] },
]
const bindings = messages.map((message, index) => ({
  evidence_span_id: `span-${index}`, message_id: message.id, field_key: 'answer', relation: 'supports',
  start_cp: 0, end_cp: Array.from(message.raw_text).length, excerpt: message.raw_text,
}))
function mount(overrides = {}) {
  const props = reactive({ modelValue: [], participants: structuredClone(participants), messages: structuredClone(messages), bindings: structuredClone(bindings), disabled: false, ...overrides })
  const updates = [], locations = []
  const root = { type: 'root', children: [] }
  const app = renderer.createApp({ render: () => h(Component, {
    ...props,
    'onUpdate:modelValue': value => { updates.push(value); props.modelValue = value },
    onLocate: value => locations.push(value),
  }) })
  app.mount(root)
  return { props, updates, locations, root, unmount: () => app.unmount() }
}
function descendants(node) { return [node, ...(node.children || []).flatMap(descendants)] }
function textOf(node) { return node.type === '#comment' ? '' : `${node.text || ''}${(node.children || []).map(textOf).join('')}` }
function button(view, label) {
  const result = descendants(view.root).find(node => node.type === 'button' && (textOf(node).includes(label) || node.props['aria-label'] === label))
  assert.ok(result, `button ${label} exists`)
  return result
}

test('recommendations require adoption and removed contributors are not automatically restored', async () => {
  const view = mount()
  try {
    assert.equal(view.updates.length, 0)
    assert.match(textOf(view.root), /根据回答依据建议：小王、小李/)
    button(view, '采用建议').props.onClick()
    await nextTick()
    assert.equal(view.props.modelValue.length, 2)
    assert.deepEqual(view.props.modelValue[0].evidence_span_ids, ['span-0'])
    button(view, '移除贡献者小王').props.onClick()
    await nextTick()
    assert.deepEqual(view.props.modelValue.map(item => item.participant_id), ['two'])
    assert.match(textOf(view.root), /根据回答依据建议：小王/)
    view.props.bindings = [...view.props.bindings]
    await nextTick()
    assert.equal(view.updates.length, 2)
    assert.deepEqual(view.props.modelValue.map(item => item.participant_id), ['two'])
  } finally { view.unmount() }
})

test('editing preserves unknown historical evidence and does not mutate input objects', async () => {
  const historical = { participant_id: 'one', contribution: '原始说明', evidence_span_ids: ['old-span', 'span-0'], imported_metadata: 'preserve' }
  const view = mount({ modelValue: [historical] })
  try {
    assert.match(textOf(view.root), /已保留原有贡献说明和证据/)
    const input = descendants(view.root).find(node => node.type === 'input' && node.props['aria-label'] === '小王的贡献说明')
    input.props.onInput({ target: { value: '修订说明' } })
    await nextTick()
    assert.equal(view.props.modelValue[0].contribution, '修订说明')
    assert.deepEqual(view.props.modelValue[0].evidence_span_ids, ['old-span', 'span-0'])
    assert.equal(view.props.modelValue[0].imported_metadata, 'preserve')
    assert.equal(historical.contribution, '原始说明')
    assert.notEqual(view.updates[0][0].evidence_span_ids, historical.evidence_span_ids)
  } finally { view.unmount() }
})

test('locating evidence emits its exact span without changing contributor data', () => {
  const view = mount({ modelValue: [{ participant_id: 'two', contribution: '检查网络', evidence_span_ids: ['span-1'] }] })
  try {
    button(view, '定位原文').props.onClick()
    assert.deepEqual(view.locations, [{ message_id: 'message-two', start_cp: 0, end_cp: 4 }])
    assert.equal(view.updates.length, 0)
  } finally { view.unmount() }
})

test('disabled controls cannot adopt, remove, edit, or navigate', () => {
  const original = { participant_id: 'one', contribution: '原始说明', evidence_span_ids: ['span-0'] }
  const view = mount({ modelValue: [original], disabled: true })
  try {
    for (const label of ['采用建议', '移除贡献者小王', '定位原文']) {
      const control = button(view, label)
      assert.equal(control.props.disabled, true)
      control.props.onClick()
    }
    const input = descendants(view.root).find(node => node.type === 'input' && node.props['aria-label'] === '小王的贡献说明')
    assert.equal(input.props.disabled, true)
    input.props.onInput({ target: { value: 'blocked' } })
    assert.equal(view.updates.length, 0)
    assert.equal(view.locations.length, 0)
    assert.equal(view.props.modelValue[0].contribution, '原始说明')
  } finally { view.unmount() }
})

test('missing eligible answer evidence shows guidance without adding arbitrary participants', () => {
  const view = mount({ bindings: [] })
  try {
    assert.match(textOf(view.root), /请先为回答或关键事实绑定本人直接发言的原文依据/)
    assert.equal(descendants(view.root).filter(node => node.type === 'button').length, 0)
    assert.equal(view.updates.length, 0)
  } finally { view.unmount() }
})
