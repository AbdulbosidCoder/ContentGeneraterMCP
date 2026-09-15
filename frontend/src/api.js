const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '');

export class AuthError extends Error {}

async function request(method, path, { body, params, form } = {}) {
  const query = params
    ? `?${new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''))}`
    : '';
  let response;
  try {
    response = await fetch(`${API_BASE}${path}${query}`, {
      method,
      credentials: 'same-origin',
      headers: form ? undefined : body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: form || (body !== undefined ? JSON.stringify(body) : undefined),
    });
  } catch (err) {
    throw new Error(`Network error: ${err.message}`);
  }

  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (response.status === 401) throw new AuthError(data.detail || 'Sign in required.');
  if (!response.ok) {
    const { detail } = data;
    const message = typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ')
        : `Request failed (HTTP ${response.status})`;
    throw new Error(message);
  }
  return data;
}

export const api = {
  get: (path, params) => request('GET', path, { params }),
  post: (path, body) => request('POST', path, { body: body ?? {} }),
  patch: (path, body) => request('PATCH', path, { body }),
  del: (path) => request('DELETE', path),
  upload: (path, file) => {
    const form = new FormData();
    form.append('file', file);
    return request('POST', path, { form });
  },
};

export const apiUrl = (path) => `${API_BASE}${path}`;

export const isMock = (text) => typeof text === 'string' && text.trimStart().startsWith('[MOCK]');

export const formatNumber = (value) => (value === null || value === undefined ? '–' : Number(value).toLocaleString());

export const labelize = (value) => (value || '').replace(/_/g, ' ');

export function timeAgo(value) {
  if (!value) return 'never';
  const seconds = Math.round((Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}
