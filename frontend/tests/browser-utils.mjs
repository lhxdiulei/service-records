import path from 'node:path'
import { pathToFileURL } from 'node:url'

export async function loadChromium() {
  const modulePath = process.env.PLAYWRIGHT_MODULE
  const specifier = modulePath ? pathToFileURL(path.resolve(modulePath)).href : 'playwright'
  try {
    return (await import(specifier)).chromium
  } catch (cause) {
    throw new Error('请安装 Playwright，或用 PLAYWRIGHT_MODULE 指定已有模块的入口路径。', { cause })
  }
}
