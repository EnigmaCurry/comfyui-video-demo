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

// ── Activities ──
export const ACTIVITIES = [
  { id: 'film-director', label: 'Film Director', subtitle: 'Keyframe-driven video production with ComfyUI' },
  { id: 'image-generator', label: 'Editor', subtitle: 'AI image generation and gallery' },
];

// ── Projects ──
export const listProjects = (activity) =>
  request('GET', activity ? `/projects?activity=${encodeURIComponent(activity)}` : '/projects');
export const getCurrentProject = () => request('GET', '/projects/current');
export const loadProject = (id) => request('POST', `/projects/${id}/load`);
export const deleteProject = (id) => request('DELETE', `/projects/${id}`);
export const createProject = (activity, name) => request('POST', '/projects/create', { activity, name });
export const renameProject = (name) => request('PUT', '/projects/current/name', { name });
export const setResolution = (width, height) => request('PUT', '/projects/current/resolution', { width, height });

// ── Premise ──
export const suggestPremise = (notes) => request('POST', '/premise/suggest', { notes });
export const setPremise = (premise, activity = 'film-director') => request('POST', '/premise/set', { premise, activity });

// ── Skip to Keyframes ──
export const skipToKeyframes = (name) => request('POST', '/skip-to-keyframes', name ? { name } : null);

// ── Story ──
export const generateStory = (scene_count, scene_duration, width, height, style = 'transition-story') =>
  request('POST', '/story/generate', { scene_count, scene_duration, width, height, style });

// ── Keyframes ──
export const addKeyframe = (prompt = '') => request('POST', '/keyframes/add', { prompt });
export const listKeyframes = () => request('GET', '/keyframes');
export const getKeyframeStatus = (id) => request('GET', `/keyframes/${id}/status`);
export const renderKeyframe = (id, opts = {}) => request('POST', `/keyframes/${id}/render`, opts);
export const rerenderKeyframe = (id, opts = {}) => request('POST', `/keyframes/${id}/rerender`, opts);
export const rewriteKeyframe = (id, instruction) => request('POST', `/keyframes/${id}/rewrite`, { instruction });
export const refineKeyframe = (id, prompt, negative_prompt) => request('POST', `/keyframes/${id}/refine`, { prompt, ...(negative_prompt ? { negative_prompt } : {}) });
export const refineUndoKeyframe = (id) => request('POST', `/keyframes/${id}/refine-undo`);
export const refineRedoKeyframe = (id) => request('POST', `/keyframes/${id}/refine-redo`);
export async function uploadKeyframeImage(id, file) {
  const form = new FormData();
  form.append('file', file);
  const resp = await fetch(`/api/keyframes/${id}/upload`, { method: 'POST', body: form });
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
  return resp.json();
}
export const updateKeyframe = (id, updates) => request('PUT', `/keyframes/${id}`, updates);
export const T2I_MODELS = [
  { id: 'hidream', label: 'HiDream' },
  { id: 'qwen_illustration', label: 'Qwen Illustration' },
  { id: 'z_image', label: 'Z-Image' },
  { id: 'flux2_klein', label: 'Flux 2 Klein', twoImage: true },
];
export const deleteKeyframe = (id) => request('DELETE', `/keyframes/${id}`);
export const duplicateKeyframe = (id) => request('POST', `/keyframes/${id}/duplicate`);
export const reorderKeyframes = (ids) => request('POST', '/keyframes/reorder', ids);
export const resetKeyframes = () => request('POST', '/keyframes/reset');
export const syncTransitions = () => request('POST', '/transitions/sync');
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
export const updateNarration = (transitionId, updates) => request('PUT', `/narration/${transitionId}`, updates);
export const renderNarration = (transitionId, opts = {}) => request('POST', `/narration/${transitionId}/render`, Object.keys(opts).length ? opts : null);
export const rewriteNarration = (transitionId, instruction) => request('POST', `/narration/rewrite/${transitionId}`, { instruction });
export const getNarrationStatus = (transitionId) => request('GET', `/narration/${transitionId}/status`);
export const regenerateNarration = (direction) => request('POST', '/narration/regenerate', direction != null ? { direction } : null);
export const setNarrationDirection = (direction, voice) => request('PUT', '/narration/direction', { direction, ...(voice != null ? { voice } : {}) });
export const setNarrationVoice = (voice) => request('PUT', '/narration/direction', { voice });
export const lockNarration = () => request('POST', '/narration/lock');
export const setNarrationActiveIndex = (activeIndex) => request('PUT', '/narration-active-index', { active_index: activeIndex });

// ── Soundtrack ──
export const listSoundtrack = () => request('GET', '/soundtrack');
export const updateSection = (id, updates) => request('PUT', `/soundtrack/${id}`, updates);
export const suggestSoundtrackPrompt = (id) => request('POST', `/soundtrack/suggest/${id}`);
export const splitSections = (groups) => request('POST', '/soundtrack/split', { groups });
export const unsplitSections = () => request('POST', '/soundtrack/unsplit');
export const renderSoundtrack = (id, seed) => request('POST', `/soundtrack/${id}/render`, seed != null ? { seed } : null);
export const remuxSoundtrack = (id, volumes) => request('POST', `/soundtrack/${id}/remux`, volumes);
export const getSoundtrackStatus = (id) => request('GET', `/soundtrack/${id}/status`);
export const lockScore = () => request('POST', '/score/lock');

// ── Final ──
export const renderFinal = () => request('POST', '/final/render');
export const getFinalStatus = () => request('GET', '/final/status');

// ── Editor / Gallery ──
export const RESOLUTIONS = [
  { label: '512x512 (1:1)', w: 512, h: 512 },
  { label: '768x512 (3:2)', w: 768, h: 512 },
  { label: '1024x576 (16:9)', w: 1024, h: 576 },
  { label: '1024x768 (4:3)', w: 1024, h: 768 },
  { label: '1024x1024 (1:1)', w: 1024, h: 1024 },
  { label: '1280x768 (5:3)', w: 1280, h: 768 },
  { label: '1920x1088 (16:9 HD)', w: 1920, h: 1088 },
  { label: '3000x3000 (1:1 XL)', w: 3000, h: 3000 },
];
export const IMAGE_FILTERS = [
  { id: 'stitch_2x', label: '2x Grid' },
  { id: 'integer_crop', label: 'Integer Crop' },
  { id: 'upscale', label: 'Upscale', slow: true },
];
export const galleryGenerate = (opts) => request('POST', '/gallery/generate', opts);
export const galleryPreviewStatus = () => request('GET', '/gallery/preview/status');
export const galleryCancel = () => request('POST', '/gallery/cancel');
export const galleryRefine = (opts) => request('POST', '/gallery/refine', opts);
export const galleryUndo = () => request('POST', '/gallery/undo');
export const gallerySave = () => request('POST', '/gallery/save');
export const galleryEdit = (imageId) => request('POST', `/gallery/edit/${imageId}`);
export const galleryFilter = (opts) => request('POST', '/gallery/filter', opts);
export const galleryFilterStatus = () => request('GET', '/gallery/filter/status');
export const galleryFilterSave = () => request('POST', '/gallery/filter/save');
export const galleryList = () => request('GET', '/gallery');
export const galleryDelete = (id) => request('DELETE', `/gallery/${id}`);
export async function galleryUpload(file) {
  const form = new FormData();
  form.append('file', file);
  const resp = await fetch('/api/gallery/upload', { method: 'POST', body: form });
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
  return resp.json();
}
