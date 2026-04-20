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
export const listProjects = () => request('GET', '/projects');
export const getCurrentProject = () => request('GET', '/projects/current');
export const loadProject = (id) => request('POST', `/projects/${id}/load`);
export const deleteProject = (id) => request('DELETE', `/projects/${id}`);

export const renameProject = (name) => request('PUT', '/projects/current/name', { name });

// ── Premise ──
export const suggestPremise = (notes) => request('POST', '/premise/suggest', { notes });
export const setPremise = (premise) => request('POST', '/premise/set', { premise });

// ── Story ──
export const generateStory = (scene_count, scene_duration, style = 'transition-story') =>
  request('POST', '/story/generate', { scene_count, scene_duration, style });

// ── Keyframes ──
export const resetKeyframes = () => request('POST', '/keyframes/reset');
export const listKeyframes = () => request('GET', '/keyframes');
export const getKeyframeStatus = (id) => request('GET', `/keyframes/${id}/status`);
export const renderKeyframe = (id, opts = {}) => request('POST', `/keyframes/${id}/render`, opts);
export const rerenderKeyframe = (id, opts = {}) => request('POST', `/keyframes/${id}/rerender`, opts);
export const updateKeyframe = (id, updates) => request('PUT', `/keyframes/${id}`, updates);
export const deleteKeyframe = (id) => request('DELETE', `/keyframes/${id}`);
export const reorderKeyframes = (ids) => request('POST', '/keyframes/reorder', ids);
export const lockKeyframe = (id) => request('POST', `/keyframes/${id}/lock`);
export const unlockKeyframe = (id) => request('POST', `/keyframes/${id}/unlock`);
export const setActiveIndex = (activeIndex) => request('PUT', '/active-index', { active_index: activeIndex });
