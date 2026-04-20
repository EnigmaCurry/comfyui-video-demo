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

// ── Projects ──

export async function listProjects() {
  return request('GET', '/projects');
}

export async function getCurrentProject() {
  return request('GET', '/projects/current');
}

export async function loadProject(id) {
  return request('POST', `/projects/${id}/load`);
}

export async function deleteProject(id) {
  return request('DELETE', `/projects/${id}`);
}

// ── Keyframes ──

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

export async function setActiveIndex(activeIndex) {
  return request('PUT', '/active-index', { active_index: activeIndex });
}
