import { apiErrorMessage } from './field-labels.js'

let csrf = ''
export async function api(path, { method = 'GET', body, version, key } = {}) {
  if (!csrf && method !== 'GET') await loadCsrf()
  const headers = {}
  if (method !== 'GET') {
    headers['X-CSRF-Token'] = csrf
    headers['Idempotency-Key'] = key || Array.from(
      crypto.getRandomValues(new Uint8Array(16)),
      b => b.toString(16).padStart(2, '0')
    ).join('')
  }
  if (version !== undefined) headers['If-Match'] = `"${version}"`
  if (body !== undefined && !(body instanceof FormData)) headers['Content-Type'] = 'application/json'
  const response = await fetch('/api/v1' + path, { method, credentials: 'same-origin', headers, body: body instanceof FormData ? body : body !== undefined ? JSON.stringify(body) : undefined })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const message = apiErrorMessage(data.detail, response.status)
    const error = new Error(message)
    error.status = response.status
    error.code = data.detail?.code
    if (response.status === 401 && path !== '/auth/login') window.dispatchEvent(new Event('session-expired'))
    throw error
  }
  if (data.csrf_token) csrf = data.csrf_token
  return data
}
export async function loadCsrf() { return api('/auth/csrf') }
export function resetCsrf() { csrf = '' }
