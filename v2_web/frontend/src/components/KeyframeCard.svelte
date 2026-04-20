<script>
  import { RefreshCw, Trash2, Check, X, ThumbsDown, Wand2, Upload } from 'lucide-svelte';
  import { rerenderKeyframe, updateKeyframe, deleteKeyframe,
           getKeyframeStatus, rewriteKeyframe, uploadKeyframeImage } from '../lib/api.js';

  let { keyframe, index, onstatus, onupdated, ondelete, onapprove, active = false, projectId = '' } = $props();

  let editing = $state(false);
  let editPrompt = $state('');
  let editingNeg = $state(false);
  let editNegPrompt = $state('');
  let rewriting = $state(false);
  let rewriteInstruction = $state('');
  let rewriteLoading = $state(false);
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

  function startEditNeg() {
    editNegPrompt = keyframe.negative_prompt || '';
    editingNeg = true;
  }

  async function saveNegEdit() {
    try {
      await updateKeyframe(keyframe.id, { negative_prompt: editNegPrompt });
      keyframe.negative_prompt = editNegPrompt;
      editingNeg = false;
      onstatus({ detail: `Updated keyframe ${index + 1} negative prompt` });
    } catch (e) {
      onstatus({ detail: `Update failed: ${e.message}` });
    }
  }

  function cancelNegEdit() {
    editingNeg = false;
  }

  function handleNegKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      saveNegEdit();
    } else if (e.key === 'Escape') {
      cancelNegEdit();
    }
  }

  function startRewrite() {
    rewriteInstruction = '';
    rewriting = true;
  }

  async function submitRewrite() {
    if (!rewriteInstruction.trim()) return;
    rewriteLoading = true;
    onstatus({ detail: `Rewriting keyframe ${index + 1}...` });
    try {
      const result = await rewriteKeyframe(keyframe.id, rewriteInstruction.trim());
      keyframe.prompt = result.prompt;
      keyframe.status = 'rendering';
      rewriting = false;
      onstatus({ detail: `Keyframe ${index + 1} rewritten and rendering...` });
    } catch (e) {
      onstatus({ detail: `Rewrite failed: ${e.message}` });
    } finally {
      rewriteLoading = false;
    }
  }

  function cancelRewrite() {
    rewriting = false;
  }

  function handleRewriteKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submitRewrite();
    } else if (e.key === 'Escape') {
      cancelRewrite();
    }
  }

  let fileInput;

  function triggerUpload() {
    fileInput.click();
  }

  async function handleUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    onstatus({ detail: `Uploading replacement for keyframe ${index + 1}...` });
    try {
      const result = await uploadKeyframeImage(keyframe.id, file);
      keyframe.image_filename = result.image_filename;
      keyframe.seed = result.seed;
      keyframe.status = result.status;
      onstatus({ detail: `Keyframe ${index + 1} replaced.` });
    } catch (err) {
      onstatus({ detail: `Upload failed: ${err.message}` });
    }
    // Reset input so same file can be re-uploaded
    e.target.value = '';
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

  function handleApprove() {
    if (onapprove) onapprove({ detail: keyframe.id });
  }

  function autoFocus(node) {
    node.focus();
    node.setSelectionRange(node.value.length, node.value.length);
  }

  function focusOverlay(node) {
    node.focus();
  }

  function handleFullscreenKeydown(e) {
    if (e.key === 'Escape') {
      fullscreen = false;
    }
  }

  async function handleFullscreenPaste(e) {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        e.preventDefault();
        const blob = item.getAsFile();
        if (!blob) continue;
        onstatus({ detail: `Pasting replacement for keyframe ${index + 1}...` });
        try {
          const result = await uploadKeyframeImage(keyframe.id, blob);
          keyframe.image_filename = result.image_filename;
          keyframe.seed = result.seed;
          keyframe.status = result.status;
          fullscreen = false;
          onstatus({ detail: `Keyframe ${index + 1} replaced from clipboard.` });
        } catch (err) {
          onstatus({ detail: `Paste failed: ${err.message}` });
        }
        return;
      }
    }
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

<div class="card" class:error={keyframe.status === 'error'} class:active>
  <div class="card-header">
    <span class="position">{index + 1}</span>
    <span class="status-badge" class:pending={keyframe.status === 'pending'}
          class:rendering={keyframe.status === 'rendering'}
          class:done={keyframe.status === 'done'}
          class:error={keyframe.status === 'error'}>
      {keyframe.status}
    </span>
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
        rows="6"
        class="edit-textarea"
        use:autoFocus
      ></textarea>
      <div class="edit-actions">
        <button class="btn-save" onclick={saveEdit}><Check size={14} /> Save</button>
        <button class="btn-cancel" onclick={cancelEdit}><X size={14} /> Cancel</button>
      </div>
    {:else}
      <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
      <p class="prompt-text clickable" onclick={startEdit}>{keyframe.prompt}</p>
    {/if}

    {#if editingNeg}
      <div class="neg-edit">
        <label class="neg-label">Negative prompt</label>
        <textarea
          bind:value={editNegPrompt}
          onkeydown={handleNegKeydown}
          rows="2"
          class="edit-textarea neg-textarea"
          placeholder="Things to avoid: text, watermark, extra limbs..."
          use:autoFocus
        ></textarea>
        <div class="edit-actions">
          <button class="btn-save" onclick={saveNegEdit}><Check size={14} /> Save</button>
          <button class="btn-cancel" onclick={cancelNegEdit}><X size={14} /> Cancel</button>
        </div>
      </div>
    {:else if keyframe.negative_prompt}
      <p class="neg-display">
        <span class="neg-label">Negative:</span> {keyframe.negative_prompt}
      </p>
    {/if}

    {#if rewriting}
      <div class="rewrite-edit">
        <label class="rewrite-label">Rewrite instruction</label>
        <textarea
          bind:value={rewriteInstruction}
          onkeydown={handleRewriteKeydown}
          rows="2"
          class="edit-textarea"
          placeholder="e.g. Make it nighttime, add rain, remove the person..."
          disabled={rewriteLoading}
          use:autoFocus
        ></textarea>
        <div class="edit-actions">
          <button class="btn-save" onclick={submitRewrite} disabled={rewriteLoading || !rewriteInstruction.trim()}>
            <Wand2 size={14} /> {rewriteLoading ? 'Rewriting...' : 'Rewrite & Render'}
          </button>
          <button class="btn-cancel" onclick={cancelRewrite} disabled={rewriteLoading}>
            <X size={14} /> Cancel
          </button>
        </div>
      </div>
    {/if}
  </div>

  <div class="card-actions">
    <button class="btn-icon" onclick={handleRerender} title="Re-render with new seed"
            disabled={keyframe.status === 'rendering'}>
      <RefreshCw size={16} />
    </button>
    <button class="btn-icon" onclick={triggerUpload} title="Upload replacement image">
      <Upload size={16} />
    </button>
    <input type="file" accept="image/*" bind:this={fileInput} onchange={handleUpload} class="hidden-input" />
    <button class="btn-icon" onclick={startRewrite} title="Rewrite with AI">
      <Wand2 size={16} />
    </button>
    <button class="btn-icon" class:btn-active={!!keyframe.negative_prompt}
            onclick={startEditNeg} title="Negative prompt">
      <ThumbsDown size={16} />
    </button>
    <button class="btn-icon btn-danger" onclick={handleDelete} title="Delete">
      <Trash2 size={16} />
    </button>
    {#if active && keyframe.status === 'done' && !editing && !editingNeg && !rewriting}
      <button class="btn-approve" onclick={handleApprove} title="Approve and render next">
        <Check size={16} /> Approve
      </button>
    {/if}
  </div>
</div>

{#if fullscreen && imageUrl}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="fullscreen-overlay" onclick={() => fullscreen = false}
       onkeydown={handleFullscreenKeydown} onpaste={handleFullscreenPaste}
       tabindex="-1" use:focusOverlay>
    <img src={imageUrl} alt="Keyframe {index + 1} full size" />
    <div class="fullscreen-hint">Ctrl+V paste / Esc close</div>
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

  .prompt-text.clickable {
    cursor: pointer;
    transition: color 0.15s;
  }

  .prompt-text.clickable:hover {
    color: var(--text);
  }

  .edit-textarea {
    width: 100%;
    resize: vertical;
    font-size: 13px;
    min-height: 60px;
  }

  .neg-edit {
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid var(--border);
  }

  .neg-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--error);
    display: block;
    margin-bottom: 4px;
  }

  .neg-textarea {
    min-height: 40px;
  }

  .neg-display {
    margin-top: 8px;
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.4;
  }

  .neg-display .neg-label {
    display: inline;
    font-size: 12px;
    margin: 0;
  }

  .rewrite-edit {
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid var(--border);
  }

  .rewrite-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--accent);
    display: block;
    margin-bottom: 4px;
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

  .hidden-input {
    display: none;
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
    margin-left: auto;
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

  .btn-active {
    color: var(--warning);
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

  .fullscreen-overlay:focus { outline: none; }

  .fullscreen-hint {
    position: absolute;
    bottom: 20px;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(0, 0, 0, 0.7);
    color: var(--text-muted);
    font-size: 12px;
    padding: 6px 14px;
    border-radius: var(--radius);
    pointer-events: none;
  }

  .fullscreen-overlay img {
    max-width: 95vw;
    max-height: 95vh;
    object-fit: contain;
    border-radius: var(--radius);
  }
</style>
