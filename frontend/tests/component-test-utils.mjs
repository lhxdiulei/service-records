import { readFile, writeFile, unlink } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import { createRenderer } from 'vue'

export async function compileComponent(name, replacements = []) {
  const { descriptor } = parse(await readFile(new URL(`../src/components/${name}.vue`, import.meta.url), 'utf8'))
  let source = compileScript(descriptor, { id: name, inlineTemplate: true }).content
  for (const [before, after] of replacements) source = source.replace(before, after)
  const target = new URL(`.${name}-${process.pid}.mjs`, import.meta.url)
  try { await writeFile(target, source); return await import(target.href) }
  finally { await unlink(target).catch(() => {}) }
}
export const renderer = createRenderer({
  createElement: type => ({ type, tagName: type.toUpperCase(), children: [], props: {}, text: '', listeners: {}, focus() { this.focused = true }, scrollIntoView() { this.scrolledIntoView = true },
    querySelector(selector) { return descendants(this).find(node => node !== this && node.type === selector) || null },
    addEventListener(name,handler) { this.listeners[name] = handler }, removeEventListener(name) { delete this.listeners[name] },
    get options() { return descendants(this).filter(node => node.type === 'option') },
  }),
  createText: text => ({ type: '#text', text }), createComment: text => ({ type: '#comment', text }),
  insert(node, parent, anchor = null) {
    if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
    node.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index >= 0) parent.children.splice(index, 0, node); else parent.children.push(node)
  },
  remove(node) { node.parent?.children.splice(node.parent.children.indexOf(node), 1) },
  setText(node, text) { node.text = text }, setElementText(node, text) { node.text = text; node.children = [] },
  patchProp(node, key, previous, next) { node.props[key] = next; if (key === 'value') { node._value = next; node.value = next } },
  parentNode: node => node.parent, nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1],
})
export function descendants(node) { return [node, ...(node.children || []).flatMap(descendants)] }
export function textOf(node) { return node.type === '#comment' ? '' : (node.text || '') + (node.children || []).map(textOf).join('') }
