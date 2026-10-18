import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile, writeFile, unlink } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive, toRaw } from 'vue'

const sourceURL = new URL('../src/components/Pagination.vue', import.meta.url)
const { descriptor } = parse(await readFile(sourceURL, 'utf8'))
const compiled = compileScript(descriptor, { id: 'pagination-test', inlineTemplate: true }).content
  .replace("import '../pagination-controls.css'", '')
const compiledURL = new URL(`.pagination-${process.pid}.mjs`, import.meta.url)
let Component
try {
  await writeFile(compiledURL, compiled)
  Component = (await import(compiledURL.href)).default
} finally { await unlink(compiledURL).catch(() => {}) }

globalThis.document ??= { activeElement: null }
const renderer = createRenderer({
  createElement: type => ({
    type, tagName: type.toUpperCase(), children: [], props: {}, text: '', listeners: {},
    addEventListener(name, listener) { this.listeners[name] = listener },
    focus() { document.activeElement = this },
    select() { this.selected = true },
  }),
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
function mount(overrides = {}) {
  const props = reactive({ page: 1, total: 25, pageSize: 10, disabled: false, ...overrides })
  const changes = []
  const root = { type: 'root', children: [] }
  const app = renderer.createApp({ render: () => h(Component, { ...props, onChange: value => { changes.push(value); props.page = value } }) })
  app.mount(root)
  return { props, changes, root, unmount: () => app.unmount() }
}
const descendants = node => [node, ...(node.children || []).flatMap(descendants)]
const textOf = node => node.type === '#comment' ? '' : `${node.text || ''}${(node.children || []).map(textOf).join('')}`
const find = (view, type) => descendants(view.root).find(node => node.type === type)
function button(view, label) {
  const node = descendants(view.root).find(node => node.type === 'button' && textOf(node) === label)
  assert.ok(node, `button ${label} exists`)
  return node
}
const event = (extra = {}) => ({ preventDefault() {}, stopPropagation() {}, ...extra })
async function openJump(view) {
  await button(view, '跳页').props.onClick()
  await nextTick()
  return find(view, 'input')
}
async function setTarget(view, value) {
  find(view, 'input').props['onUpdate:modelValue'](value)
  await nextTick()
}

test('empty and single-page lists show totals without navigation or numeric inputs', () => {
  for (const total of [0, 1, 10]) {
    const view = mount({ total })
    try {
      assert.match(textOf(view.root), new RegExp(`共 ${total} 条 · 每页 10 条`))
      assert.equal(descendants(view.root).filter(node => ['button', 'input', 'form'].includes(node.type)).length, 0)
      assert.deepEqual(view.changes, [])
    } finally { view.unmount() }
  }
})

test('multi-page lists expose previous/next with page summary and preserve the page size contract', async () => {
  const view = mount({ total: 21 })
  try {
    assert.deepEqual(descendants(view.root).filter(node => node.type === 'button').map(textOf), ['上一页', '下一页', '跳页'])
    assert.match(textOf(view.root), /第 1 \/ 3 页/)
    assert.equal(button(view, '上一页').props.disabled, true)
    assert.equal(find(view, 'input'), undefined)
    button(view, '下一页').props.onClick()
    await nextTick()
    button(view, '下一页').props.onClick()
    await nextTick()
    assert.match(textOf(view.root), /第 3 \/ 3 页/)
    assert.equal(button(view, '下一页').props.disabled, true)
    button(view, '下一页').props.onClick()
    button(view, '上一页').props.onClick()
    await nextTick()
    assert.deepEqual(view.changes, [2, 3, 2])
    view.props.pageSize = 20
    await nextTick()
    assert.match(textOf(view.root), /每页 20 条/)
    assert.match(textOf(view.root), /第 2 \/ 2 页/)
  } finally { view.unmount() }
})

test('expanded jump controls reach first, last, and arbitrary pages, then close', async () => {
  const view = mount({ page: 4, total: 107 })
  try {
    const input = await openJump(view)
    assert.equal(toRaw(document.activeElement), input)
    assert.equal(input.selected, true)
    assert.equal(button(view, '收起跳页').props['aria-expanded'], true)
    assert.equal(input.props.min, '1')
    assert.equal(input.props.max, 11)
    button(view, '末页').props.onClick()
    await nextTick()
    assert.equal(find(view, 'form'), undefined)
    await openJump(view)
    assert.equal(button(view, '末页').props.disabled, true)
    button(view, '首页').props.onClick()
    await nextTick()
    await openJump(view)
    assert.equal(button(view, '首页').props.disabled, true)
    await setTarget(view, 7)
    find(view, 'form').props.onSubmit(event())
    await nextTick()
    assert.deepEqual(view.changes, [11, 1, 7])
    assert.equal(button(view, '跳页').props['aria-expanded'], false)
  } finally { view.unmount() }
})

test('invalid, fractional, empty, and unchanged page targets cannot emit navigation', async () => {
  const view = mount({ page: 2, total: 34 })
  try {
    await openJump(view)
    for (const target of ['', 0, -1, 5, 1.5, 'invalid', Infinity]) {
      await setTarget(view, target)
      assert.equal(button(view, '确定').props.disabled, true)
      assert.equal(find(view, 'input').props['aria-invalid'], true)
      find(view, 'form').props.onSubmit(event())
      assert.deepEqual(view.changes, [])
    }
    await setTarget(view, 2)
    assert.equal(button(view, '确定').props.disabled, true)
    find(view, 'form').props.onSubmit(event())
    assert.deepEqual(view.changes, [])
    await setTarget(view, 3)
    assert.equal(button(view, '确定').props.disabled, false)
    assert.equal(find(view, 'input').props['aria-invalid'], false)
  } finally { view.unmount() }
})

test('disabled pagination blocks every navigation action and cannot expand', async () => {
  const view = mount({ page: 2, total: 34, disabled: true })
  try {
    for (const label of ['上一页', '下一页', '跳页']) {
      const control = button(view, label)
      assert.equal(control.props.disabled, true)
      await control.props.onClick()
    }
    assert.equal(find(view, 'form'), undefined)
    assert.deepEqual(view.changes, [])
    view.props.disabled = false
    await nextTick()
    await openJump(view)
    await setTarget(view, 3)
    view.props.disabled = true
    await nextTick()
    assert.equal(find(view, 'input').props.disabled, true)
    for (const label of ['首页', '末页', '确定']) assert.equal(button(view, label).props.disabled, true)
    button(view, '首页').props.onClick()
    button(view, '末页').props.onClick()
    find(view, 'form').props.onSubmit(event())
    assert.deepEqual(view.changes, [])
  } finally { view.unmount() }
})

test('Escape restores toggle focus, and a filtered single page closes the jump panel', async () => {
  const view = mount({ page: 2, total: 34 })
  try {
    await openJump(view)
    find(view, 'form').props.onKeydown(event({ key: 'Escape' }))
    await nextTick()
    assert.equal(find(view, 'form'), undefined)
    assert.equal(toRaw(document.activeElement), button(view, '跳页'))
    assert.deepEqual(view.changes, [])
    await openJump(view)
    view.props.total = 8
    view.props.page = 1
    await nextTick()
    assert.equal(find(view, 'form'), undefined)
    assert.equal(find(view, 'button'), undefined)
    view.props.total = 35
    await nextTick()
    assert.equal(find(view, 'form'), undefined)
    await openJump(view)
    assert.equal(find(view, 'input').value, 1)
  } finally { view.unmount() }
})
