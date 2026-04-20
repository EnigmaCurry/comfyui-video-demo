/**
 * Backend API client for the film director.
 */

const BASE = '/api';

async function request(method, path, body = null) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body !== null) {
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(`${BASE}${path}`, opts);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
  }
  return resp.json();
}

export async function listKeyframes() {
  return request('GET', '/keyframes');
}

export async function generateKeyframes(theme, count, style = 'transition-story') {
  return request('POST', '/keyframes/generate', { theme, count, style });
}

export async function getKeyframeStatus(id) {
  return request('GET', `/keyframes/${id}/status`);
}

export async function renderKeyframe(id, opts = {}) {
  return request('POST', `/keyframes/${id}/render`, opts);
}

export async function rerenderKeyframe(id, opts = {}) {
  return request('POST', `/keyframes/${id}/rerender`, opts);
}

export async function updateKeyframe(id, updates) {
  return request('PUT', `/keyframes/${id}`, updates);
}

export async function deleteKeyframe(id) {
  return request('DELETE', `/keyframes/${id}`);
}

export async function reorderKeyframes(ids) {
  return request('POST', '/keyframes/reorder', ids);
}

export async function lockKeyframe(id) {
  return request('POST', `/keyframes/${id}/lock`);
}

export async function unlockKeyframe(id) {
  return request('POST', `/keyframes/${id}/unlock`);
}
