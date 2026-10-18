import test from 'node:test'
import assert from 'node:assert/strict'
import { h, nextTick, reactive } from 'vue'
import { compileComponent, renderer, descendants, textOf } from './component-test-utils.mjs'
const { default: Component } = await compileComponent('DashboardMetrics')

test('all four cards are native buttons and navigate even when their count is zero', async () => {
  const events = [], props = reactive({ overview: { tickets: 19, official_tickets: 1, qa: 7, official_qa: 1, reviews: 1, unassigned_messages: 0 }, disabled: false })
  const root = { children: [] }, app = renderer.createApp({ render: () => h(Component, { ...props, onNavigate: value => events.push(value) }) })
  app.mount(root)
  try {
    const buttons = descendants(root).filter(node => node.type === 'button')
    assert.equal(buttons.length, 4)
    assert.deepEqual(buttons.map(b => b.props['aria-label']), ['查看服务工单', '查看知识 QA', '查看待审核', '查看待归属消息'])
    for (const button of buttons) button.props.onClick()
    assert.deepEqual(events, ['tickets', 'qa', 'reviews', 'messages'])
    assert.match(textOf(root), /19/)
    props.disabled = true; await nextTick()
    for (const button of buttons) { assert.equal(button.props.disabled, true); button.props.onClick() }
    assert.equal(events.length, 4)
  } finally { app.unmount() }
})
