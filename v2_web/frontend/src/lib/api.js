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
export const listKeyframes = () => request('GET', '/keyframes');
export const getKeyframeStatus = (id) => request('GET', `/keyframes/${id}/status`);
export const renderKeyframe = (id, opts = {}) => request('POST', `/keyframes/${id}/render`, opts);
export const rerenderKeyframe = (id, opts = {}) => request('POST', `/keyframes/${id}/rerender`, opts);
export const rewriteKeyframe = (id, instruction) => request('POST', `/keyframes/${id}/rewrite`, { instruction });
export const updateKeyframe = (id, updates) => request('PUT', `/keyframes/${id}`, updates);
export const deleteKeyframe = (id) => request('DELETE', `/keyframes/${id}`);
export const reorderKeyframes = (ids) => request('POST', '/keyframes/reorder', ids);
export const resetKeyframes = () => request('POST', '/keyframes/reset');
export const lockKeyframes = () => request('POST', '/keyframes/lock');
export const autoCreateKeyframes = () => request('POST', '/keyframes/auto-create');
export const setActiveIndex = (activeIndex) => request('PUT', '/active-index', { active_index: activeIndex });

// ── Transitions ──
export const listTransitions = () => request('GET', '/transitions');
export const getTransitionStatus = (id) => request('GET', `/transitions/${id}/status`);
export const renderTransition = (id, opts = {}) => request('POST', `/transitions/${id}/render`, opts);
export const rerenderTransition = (id, opts = {}) => request('POST', `/transitions/${id}/rerender`, opts);
export const updateTransition = (id, updates) => request('PUT', `/transitions/${id}`, updates);
export const resetTransitions = () => request('POST', '/transitions/reset');
export const autoCreateTransitions = () => request('POST', '/transitions/auto-create');
export const lockTransitions = () => request('POST', '/transitions/lock');
export const setTransitionActiveIndex = (activeIndex) => request('PUT', '/transition-active-index', { active_index: activeIndex });

// ── Narration ──
export const updateNarration = (transitionId, narration) => request('PUT', `/narration/${transitionId}`, { narration });
export const regenerateNarration = () => request('POST', '/narration/regenerate');
export const setNarrationActiveIndex = (activeIndex) => request('PUT', '/narration-active-index', { active_index: activeIndex });
