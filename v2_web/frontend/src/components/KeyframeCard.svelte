<script>
  import { RefreshCw, Pencil, Lock, Unlock, Trash2, Check, X, ChevronRight } from 'lucide-svelte';
  import { rerenderKeyframe, updateKeyframe, deleteKeyframe,
           lockKeyframe, unlockKeyframe, getKeyframeStatus } from '../lib/api.js';

  let { keyframe, index, onstatus, onupdated, ondelete, onapprove, active = false, projectId = '' } = $props();

  let editing = $state(false);
  let editPrompt = $state('');
  let polling = $state(false);
  let imageUrl = $state(null);
  let fullscreen = $state(false);

  $effect(() => {
    if (keyframe.image_filename && projectId) {
      // Cache-bust with seed so re-renders show the new image
      const bust = keyframe.seed || Date.now();
      imageUrl = `/api/projects/${projectId}/images/${keyframe.image_filename}?v=${bust}`;
    } else {
      imageUrl = null;
    }
  });

  $effect(() => {
    if (keyframe.status === 'rendering' && !polling) {
      polling = true;
      pollStatus();
    }
  });

  async function pollStatus() {
    while (keyframe.status === 'rendering') {
      await new Promise(r => setTimeout(r, 2000));
      try {
        const status = await getKeyframeStatus(keyframe.id);
        keyframe.status = status.status;
        keyframe.error_message = status.error_message;
        if (status.seed != null) {
          keyframe.seed = status.seed;
        }
        if (status.image_url) {
          keyframe.image_filename = status.image_url.split('/').pop();
        }
      } catch {
        break;
      }
    }
    polling = false;
    if (onupdated) onupdated({ detail: null });
  }

  async function handleRerender() {
    try {
      onstatus({ detail: `Re-rendering keyframe ${index + 1}...` });
      const result = await rerenderKeyframe(keyframe.id);
      keyframe.status = result.status;
    } catch (e) {
      onstatus({ detail: `Re-render failed: ${e.message}` });
    }
  }

  function startEdit() {
    editPrompt = keyframe.prompt;
    editing = true;
  }

  async function saveEdit() {
    try {
      await updateKeyframe(keyframe.id, { prompt: editPrompt });
      keyframe.prompt = editPrompt;
      editing = false;
      onstatus({ detail: `Updated keyframe ${index + 1} prompt` });
    } catch (e) {
      onstatus({ detail: `Update failed: ${e.message}` });
    }
  }

  function cancelEdit() {
    editing = false;
  }

  async function handleDelete() {
    try {
      await deleteKeyframe(keyframe.id);
      ondelete({ detail: keyframe.id });
      onstatus({ detail: `Deleted keyframe ${index + 1}` });
    } catch (e) {
      onstatus({ detail: `Delete failed: ${e.message}` });
    }
  }

  async function toggleLock() {
    try {
      if (keyframe.locked) {
        await unlockKeyframe(keyframe.id);
        keyframe.locked = false;
      } else {
        await lockKeyframe(keyframe.id);
        keyframe.locked = true;
      }
    } catch (e) {
      onstatus({ detail: `Lock toggle failed: ${e.message}` });
    }
  }

  function handleApprove() {
    if (onapprove) onapprove({ detail: keyframe.id });
  }

  function handleEditKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      saveEdit();
    } else if (e.key === 'Escape') {
      cancelEdit();
    }
  }
</script>

<div class="card" class:locked={keyframe.locked} class:error={keyframe.status === 'error'} class:active>
  <div class="card-header">
    <span class="position">{index + 1}</span>
    <span class="status-badge" class:pending={keyframe.status === 'pending'}
          class:rendering={keyframe.status === 'rendering'}
          class:done={keyframe.status === 'done'}
          class:error={keyframe.status === 'error'}>
      {keyframe.status}
    </span>
    {#if keyframe.locked}
      <span class="lock-badge">locked</span>
    {/if}
  </div>

  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="image-area" onclick={() => imageUrl && (fullscreen = true)}>
    {#if keyframe.status === 'rendering'}
      <div class="spinner-container">
        <div class="spinner"></div>
        <span>Rendering...</span>
      </div>
    {:else if imageUrl}
      <img src={imageUrl} alt="Keyframe {index + 1}" />
    {:else if keyframe.status === 'error'}
      <div class="error-container">
        <span>Error</span>
        <small>{keyframe.error_message || 'Unknown error'}</small>
      </div>
    {:else}
      <div class="placeholder">
        <span>Pending</span>
      </div>
    {/if}
  </div>

  <div class="card-body">
    {#if editing}
      <textarea
        bind:value={editPrompt}
        onkeydown={handleEditKeydown}
        rows="3"
        class="edit-textarea"
      ></textarea>
      <div class="edit-actions">
        <button class="btn-save" onclick={saveEdit}><Check size={14} /> Save</button>
        <button class="btn-cancel" onclick={cancelEdit}><X size={14} /> Cancel</button>
      </div>
    {:else}
      <p class="prompt-text">{keyframe.prompt}</p>
    {/if}
  </div>

  <div class="card-actions">
    {#if active && keyframe.status === 'done'}
      <button class="btn-approve" onclick={handleApprove} title="Approve and render next">
        <Check size={16} /> Approve
      </button>
    {/if}
    <button class="btn-icon" onclick={handleRerender} title="Re-render with new seed"
            disabled={keyframe.status === 'rendering'}>
      <RefreshCw size={16} />
    </button>
    <button class="btn-icon" onclick={startEdit} title="Edit prompt">
      <Pencil size={16} />
    </button>
    <button class="btn-icon" onclick={toggleLock}
            title={keyframe.locked ? 'Unlock' : 'Lock'}>
      {#if keyframe.locked}
        <Lock size={16} />
      {:else}
        <Unlock size={16} />
      {/if}
    </button>
    <button class="btn-icon btn-danger" onclick={handleDelete} title="Delete">
      <Trash2 size={16} />
    </button>
  </div>
</div>

{#if fullscreen && imageUrl}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="fullscreen-overlay" onclick={() => fullscreen = false}>
    <img src={imageUrl} alt="Keyframe {index + 1} full size" />
  </div>
{/if}

<style>
  .card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
    transition: all 0.15s ease;
    display: flex;
    flex-direction: column;
  }

  .card:hover {
    border-color: var(--text-muted);
  }

  .card.active {
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent);
  }

  .card.locked {
    border-color: var(--locked);
    box-shadow: 0 0 0 1px var(--locked);
  }

  .card.error {
    border-color: var(--error);
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

  .status-badge {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: 500;
  }

  .status-badge.pending { background: var(--accent-bg); color: var(--accent); }
  .status-badge.rendering { background: var(--accent-bg); color: var(--accent-hover); }
  .status-badge.done { background: rgba(34, 197, 94, 0.15); color: var(--success); }
  .status-badge.error { background: rgba(239, 68, 68, 0.15); color: var(--error); }

  .lock-badge {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: 500;
    background: var(--locked-bg);
    color: var(--locked);
    margin-left: auto;
  }

  .image-area {
    aspect-ratio: 16 / 9;
    background: var(--bg);
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    cursor: pointer;
  }

  .image-area img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .spinner-container, .error-container, .placeholder {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    color: var(--text-muted);
    font-size: 13px;
  }

  .spinner {
    width: 28px;
    height: 28px;
    border: 3px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  .error-container small {
    max-width: 200px;
    text-align: center;
    word-break: break-word;
    color: var(--error);
  }

  .card-body {
    padding: 12px 14px;
    flex: 1;
  }

  .prompt-text {
    font-size: 13px;
    color: var(--text-dim);
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .edit-textarea {
    width: 100%;
    resize: vertical;
    font-size: 13px;
    min-height: 60px;
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

  .btn-approve {
    background: var(--success);
    color: white;
    font-size: 13px;
    font-weight: 500;
    padding: 6px 14px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-right: auto;
  }

  .btn-approve:hover {
    filter: brightness(1.1);
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

  .btn-danger:hover:not(:disabled) {
    color: var(--error);
  }

  .fullscreen-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.9);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    cursor: pointer;
  }

  .fullscreen-overlay img {
    max-width: 95vw;
    max-height: 95vh;
    object-fit: contain;
    border-radius: var(--radius);
  }
</style>
