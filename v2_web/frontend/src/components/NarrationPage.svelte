<script>
  import { Pencil, Check, X, RotateCcw, Play } from 'lucide-svelte';
  import { updateNarration, regenerateNarration, setNarrationActiveIndex,
           setNarrationDirection, renderNarration, getNarrationStatus } from '../lib/api.js';

  let { transitions = $bindable([]), keyframes = [], projectId = '',
        direction: initialDirection = '', onstatus, onreset } = $props();

  const DEFAULT_DIRECTION = "A contemplative, poetic narrator experiencing the scene firsthand. Stream of consciousness, present tense.";
  let activeIndex = $state(-1);
  let initialized = $state(false);
  let editing = $state({});
  let editTexts = $state({});
  const VOICES = [
    'butler', 'despotism-doc', 'feynman', 'kyle', 'linus',
    'mcgill', 'mckenna', 'mulgrew', 'nixon', 'paul-atreides', 'steve', 'wexler',
  ];
  let direction = $state(initialDirection || DEFAULT_DIRECTION);
  let voice = $state('despotism-doc');
  let regenerating = $state(false);
  let directionDirty = $state(false);
  let polling = $state({});

  $effect(() => { direction = initialDirection || DEFAULT_DIRECTION; });

  $effect(() => {
    if (initialized || transitions.length === 0) return;
    initialized = true;
    // Find the first transition that hasn't been narration-rendered
    const firstPending = transitions.findIndex(t => t.narration_status !== 'done');
    if (firstPending === -1) {
      activeIndex = transitions.length - 1;
    } else if (firstPending === 0) {
      activeIndex = 0;
    } else {
      activeIndex = firstPending - 1;
    }
  });

  // Poll any that are rendering on load
  $effect(() => {
    for (const tr of transitions) {
      if (tr.narration_status === 'rendering' && !polling[tr.id]) {
        pollStatus(tr);
      }
    }
  });

  let allDone = $derived(transitions.length > 0 && transitions.every(t => t.narration_status === 'done'));

  function videoUrl(tr) {
    if (!tr?.video_filename || !projectId) return null;
    return `/api/projects/${projectId}/videos/${tr.video_filename}?v=${tr.seed || 0}`;
  }

  function narratedVideoUrl(tr) {
    if (!tr?.narrated_video_filename || !projectId) return null;
    return `/api/projects/${projectId}/videos/${tr.narrated_video_filename}?v=${tr.narration_status}`;
  }

  function startEdit(tr) {
    editTexts[tr.id] = tr.narration;
    editing[tr.id] = true;
  }

  async function saveEdit(tr) {
    try {
      await updateNarration(tr.id, editTexts[tr.id]);
      tr.narration = editTexts[tr.id];
      // Narration text changed — reset render status
      tr.narration_status = 'pending';
      tr.narrated_video_filename = null;
      editing[tr.id] = false;
      onstatus({ detail: `Updated narration for transition ${tr.position + 1}` });
    } catch (e) {
      onstatus({ detail: `Update failed: ${e.message}` });
    }
  }

  function cancelEdit(tr) { editing[tr.id] = false; }

  async function handleRender(tr) {
    onstatus({ detail: `Rendering narration ${tr.position + 1}...` });
    tr.narration_status = 'rendering';
    try {
      await renderNarration(tr.id, `${voice}.wav`);
      pollStatus(tr);
    } catch (e) {
      onstatus({ detail: `Render failed: ${e.message}` });
      tr.narration_status = 'error';
    }
  }

  async function pollStatus(tr) {
    if (polling[tr.id]) return;
    polling[tr.id] = true;
    while (tr.narration_status === 'rendering') {
      await new Promise(r => setTimeout(r, 3000));
      try {
        const status = await getNarrationStatus(tr.id);
        tr.narration_status = status.status;
        tr.narration_error = status.error;
        if (status.video_url) {
          tr.narrated_video_filename = status.video_url.split('/').pop();
        }
      } catch { break; }
    }
    polling[tr.id] = false;
  }

  function handleApprove() {
    const nextIndex = activeIndex + 1;
    if (nextIndex < transitions.length) {
      activeIndex = nextIndex;
      setNarrationActiveIndex(activeIndex);
      onstatus({ detail: `Approved #${activeIndex}. Review narration #${nextIndex + 1}...` });
    } else {
      activeIndex = transitions.length;
      setNarrationActiveIndex(activeIndex);
      onstatus({ detail: 'All narration approved!' });
    }
  }

  async function handleSaveDirection() {
    try {
      await setNarrationDirection(direction);
      directionDirty = false;
      onstatus({ detail: 'Narration direction saved.' });
    } catch (e) {
      onstatus({ detail: `Save failed: ${e.message}` });
    }
  }

  function handleDirectionInput() { directionDirty = true; }

  async function handleRegenerate() {
    if (!confirm('Regenerate all narration text? Your edits and renders will be lost.')) return;
    regenerating = true;
    onstatus({ detail: 'Regenerating narration...' });
    try {
      const data = await regenerateNarration(direction);
      if (onreset) onreset({ detail: data.project });
      directionDirty = false;
      onstatus({ detail: 'Narration regenerated.' });
      initialized = false;
    } catch (e) {
      onstatus({ detail: `Failed: ${e.message}` });
    } finally {
      regenerating = false;
    }
  }

  function autoFocus(node) {
    node.focus();
    node.setSelectionRange(node.value.length, node.value.length);
  }

  function editKeydown(e, tr) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEdit(tr); }
    else if (e.key === 'Escape') { cancelEdit(tr); }
  }
</script>

{#if transitions.length > 0}
  <div class="direction-panel">
    <h3>Narrator Direction</h3>
    <p class="direction-hint">
      Define who is speaking — their voice, perspective, vocabulary, and mannerisms. This drives all narration generation.
    </p>
    <textarea
      class="direction-input"
      placeholder="e.g. First person as the main character, stream of consciousness. Short fragmented thoughts. Present tense."
      bind:value={direction}
      oninput={handleDirectionInput}
      rows="3"
    ></textarea>
    <div class="voice-row">
      <label for="voice-select">Voice</label>
      <select id="voice-select" bind:value={voice} class="voice-select">
        {#each VOICES as v}
          <option value={v}>{v}</option>
        {/each}
      </select>
    </div>

    <div class="direction-actions">
      {#if directionDirty}
        <button class="btn-save-dir" onclick={handleSaveDirection}>Save Direction</button>
      {/if}
      <button class="toolbar-btn" onclick={handleRegenerate} disabled={regenerating}>
        <RotateCcw size={14} /> {regenerating ? 'Regenerating...' : 'Regenerate All'}
      </button>
    </div>
  </div>

  <div class="narrations">
    {#each transitions as tr, i (tr.id)}
      {@const isActive = i === activeIndex}
      {@const isEditing = editing[tr.id]}
      {@const hasNarratedVideo = tr.narration_status === 'done' && narratedVideoUrl(tr)}

      <div class="narration-card" class:active={isActive}>
        <div class="card-header">
          <span class="position">{i + 1}</span>
          <span class="label">Transition {tr.position + 1}</span>
          <span class="status-badge"
                class:pending={tr.narration_status === 'pending'}
                class:rendering={tr.narration_status === 'rendering'}
                class:done={tr.narration_status === 'done'}
                class:error={tr.narration_status === 'error'}>
            {tr.narration_status === 'done' ? 'rendered' : tr.narration_status}
          </span>
        </div>

        <div class="card-content">
          <div class="video-thumb">
            {#if hasNarratedVideo}
              <!-- svelte-ignore a11y_media_has_caption -->
              <video src={narratedVideoUrl(tr)} controls loop></video>
            {:else if tr.narration_status === 'rendering'}
              <div class="render-overlay">
                <div class="spinner"></div>
                <span>Rendering...</span>
              </div>
              {#if videoUrl(tr)}
                <!-- svelte-ignore a11y_media_has_caption -->
                <video src={videoUrl(tr)} loop muted></video>
              {/if}
            {:else if videoUrl(tr)}
              <!-- svelte-ignore a11y_media_has_caption -->
              <video src={videoUrl(tr)} loop muted></video>
            {/if}
          </div>

          <div class="narration-body">
            <p class="scene-prompt">{tr.prompt}</p>

            {#if isEditing}
              <textarea
                bind:value={editTexts[tr.id]}
                onkeydown={(e) => editKeydown(e, tr)}
                rows="4"
                class="edit-textarea"
                use:autoFocus
              ></textarea>
              <div class="edit-actions">
                <button class="btn-save" onclick={() => saveEdit(tr)}><Check size={14} /> Save</button>
                <button class="btn-cancel" onclick={() => cancelEdit(tr)}><X size={14} /> Cancel</button>
              </div>
            {:else}
              <blockquote class="narration-text">
                {tr.narration || '(no narration)'}
              </blockquote>
            {/if}

            {#if tr.narration_status === 'error'}
              <p class="error-msg">{tr.narration_error || 'Unknown error'}</p>
            {/if}
          </div>
        </div>

        <div class="card-actions">
          <button class="btn-icon" onclick={() => startEdit(tr)} title="Edit narration">
            <Pencil size={16} />
          </button>
          {#if isActive && !isEditing}
            {#if tr.narration_status === 'done'}
              <button class="btn-approve" onclick={handleApprove} title="Approve narration">
                <Check size={16} /> Approve
              </button>
            {:else if tr.narration_status !== 'rendering'}
              <button class="btn-render" onclick={() => handleRender(tr)} title="Render narration audio">
                <Play size={16} /> Render
              </button>
            {/if}
          {/if}
        </div>
      </div>
    {/each}
  </div>

  {#if allDone}
    <div class="all-done">
      <span>All narration rendered and approved!</span>
    </div>
  {/if}
{:else}
  <div class="empty">
    <p>No narration yet. Approve all transitions first.</p>
  </div>
{/if}

<style>
  .direction-panel {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 20px;
    margin-bottom: 20px;
  }

  .direction-panel h3 {
    font-size: 16px;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 4px;
  }

  .direction-hint {
    font-size: 13px;
    color: var(--text-muted);
    margin-bottom: 10px;
  }

  .direction-input {
    width: 100%;
    resize: vertical;
    font-size: 14px;
    line-height: 1.6;
    margin-bottom: 10px;
  }

  .voice-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
  }

  .voice-row label {
    font-size: 14px;
    color: var(--text-dim);
  }

  .voice-select {
    font-family: inherit;
    font-size: 14px;
    color: var(--text);
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 6px 12px;
    outline: none;
  }

  .voice-select:focus {
    border-color: var(--border-focus);
  }

  .direction-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }

  .btn-save-dir {
    background: var(--accent);
    color: white;
    font-size: 13px;
    font-weight: 500;
    padding: 6px 16px;
  }

  .btn-save-dir:hover { background: var(--accent-hover); }

  .toolbar-btn {
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border);
    font-size: 13px;
    padding: 6px 14px;
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }

  .toolbar-btn:hover:not(:disabled) {
    color: var(--text-dim);
    border-color: var(--text-muted);
  }

  .narrations {
    display: flex;
    flex-direction: column;
    gap: 16px;
    margin-bottom: 24px;
  }

  .narration-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }

  .narration-card.active {
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent);
  }

  .card-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
  }

  .position {
    font-weight: 700;
    font-size: 18px;
    color: var(--text);
    min-width: 24px;
  }

  .label { font-size: 13px; color: var(--text-muted); }

  .status-badge {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: 500;
    margin-left: auto;
  }

  .status-badge.pending { background: var(--accent-bg); color: var(--accent); }
  .status-badge.rendering { background: var(--accent-bg); color: var(--accent-hover); }
  .status-badge.done { background: rgba(34, 197, 94, 0.15); color: var(--success); }
  .status-badge.error { background: rgba(239, 68, 68, 0.15); color: var(--error); }

  .card-content {
    display: flex;
    gap: 16px;
    padding: 14px;
  }

  .video-thumb {
    width: 240px;
    flex-shrink: 0;
    border-radius: var(--radius);
    overflow: hidden;
    background: #000;
    position: relative;
  }

  .video-thumb video {
    width: 100%;
    display: block;
  }

  .render-overlay {
    position: absolute;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    color: white;
    font-size: 13px;
    z-index: 1;
  }

  .spinner {
    width: 24px;
    height: 24px;
    border: 3px solid rgba(255,255,255,0.3);
    border-top-color: white;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  .narration-body {
    flex: 1;
    min-width: 0;
  }

  .scene-prompt {
    font-size: 12px;
    color: var(--text-muted);
    margin-bottom: 10px;
    line-height: 1.4;
    font-style: italic;
  }

  .narration-text {
    font-size: 15px;
    color: var(--text);
    line-height: 1.6;
    margin: 0;
    padding: 12px 16px;
    border-left: 3px solid var(--accent);
    background: var(--bg);
    border-radius: 0 var(--radius) var(--radius) 0;
  }

  .error-msg {
    margin-top: 8px;
    font-size: 12px;
    color: var(--error);
  }

  .edit-textarea {
    width: 100%;
    resize: vertical;
    font-size: 15px;
    min-height: 80px;
    line-height: 1.6;
  }

  .edit-actions {
    display: flex;
    gap: 6px;
    margin-top: 8px;
  }

  .btn-save {
    background: var(--accent);
    color: white;
    font-size: 12px;
    padding: 4px 12px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .btn-cancel {
    background: transparent;
    color: var(--text-dim);
    border: 1px solid var(--border);
    font-size: 12px;
    padding: 4px 12px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .card-actions {
    display: flex;
    gap: 4px;
    padding: 8px 14px;
    border-top: 1px solid var(--border);
    align-items: center;
  }

  .btn-icon {
    background: transparent;
    color: var(--text-dim);
    padding: 6px 10px;
    font-size: 16px;
    border-radius: var(--radius);
  }

  .btn-icon:hover:not(:disabled) {
    background: var(--bg-card-hover);
    color: var(--text);
  }

  .btn-render {
    background: var(--accent);
    color: white;
    font-size: 13px;
    font-weight: 500;
    padding: 6px 14px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-left: auto;
  }

  .btn-render:hover { background: var(--accent-hover); }

  .btn-approve {
    background: var(--success);
    color: white;
    font-size: 13px;
    font-weight: 500;
    padding: 6px 14px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-left: auto;
  }

  .btn-approve:hover { filter: brightness(1.1); }

  .all-done {
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 20px 24px;
    margin-bottom: 24px;
  }

  .all-done span {
    font-size: 16px;
    font-weight: 500;
    color: var(--success);
  }

  .empty {
    text-align: center;
    padding: 80px 20px;
    color: var(--text-muted);
    border: 2px dashed var(--border);
    border-radius: var(--radius-lg);
    margin-bottom: 24px;
  }
</style>
