<script>
  import { RefreshCw, Trash2, Check, X, ThumbsDown, Wand2, Upload, Paintbrush, Undo2, Redo2, Copy } from 'lucide-svelte';
  import { rerenderKeyframe, updateKeyframe, deleteKeyframe, duplicateKeyframe,
           getKeyframeStatus, rewriteKeyframe, refineKeyframe, refineUndoKeyframe,
           refineRedoKeyframe, uploadKeyframeImage, T2I_MODELS } from '../lib/api.js';

  let { keyframe, index, onstatus, onupdated, ondelete, onduplicate, projectId = '' } = $props();

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
        if (status.refinement_history) {
          keyframe.refinement_history = status.refinement_history;
        }
        if (status.refinement_index != null) {
          keyframe.refinement_index = status.refinement_index;
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
      keyframe.refinement_history = [];
      keyframe.refinement_index = -1;
      refining = false;
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
      const wasBlank = !keyframe.prompt;
      await updateKeyframe(keyframe.id, { prompt: editPrompt });
      keyframe.prompt = editPrompt;
      editing = false;
      if (wasBlank && editPrompt.trim()) {
        onstatus({ detail: `Rendering keyframe ${index + 1}...` });
        const result = await rerenderKeyframe(keyframe.id);
        keyframe.status = result.status;
      } else {
        onstatus({ detail: `Updated keyframe ${index + 1} prompt` });
      }
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

  let refining = $state(false);
  let refinePrompt = $state('');
  let refineLoading = $state(false);

  let refineHistory = $derived(keyframe.refinement_history || []);
  let refineIndex = $derived(keyframe.refinement_index ?? -1);
  let canRefineUndo = $derived(refineIndex > 0 && keyframe.status !== 'rendering');
  let canRefineRedo = $derived(refineIndex >= 0 && refineIndex < refineHistory.length - 1 && keyframe.status !== 'rendering');

  function startRefine() {
    refinePrompt = '';
    refining = true;
  }

  async function submitRefine() {
    if (!refinePrompt.trim()) return;
    refineLoading = true;
    onstatus({ detail: `Refining keyframe ${index + 1}...` });
    try {
      const result = await refineKeyframe(keyframe.id, refinePrompt.trim(), keyframe.negative_prompt);
      keyframe.status = 'rendering';
      refinePrompt = '';
      onstatus({ detail: `Keyframe ${index + 1} refining...` });
    } catch (e) {
      onstatus({ detail: `Refine failed: ${e.message}` });
    } finally {
      refineLoading = false;
    }
  }

  function applyRefineResult(result) {
    keyframe.status = result.status;
    keyframe.seed = result.seed;
    keyframe.refinement_history = result.refinement_history;
    keyframe.refinement_index = result.refinement_index;
    if (result.image_url) {
      keyframe.image_filename = result.image_url.split('/').pop();
    }
  }

  async function handleRefineUndo() {
    onstatus({ detail: `Undoing refinement on keyframe ${index + 1}...` });
    try {
      applyRefineResult(await refineUndoKeyframe(keyframe.id));
      onstatus({ detail: 'Refinement undone.' });
    } catch (e) {
      onstatus({ detail: `Undo failed: ${e.message}` });
    }
  }

  async function handleRefineRedo() {
    onstatus({ detail: `Redoing refinement on keyframe ${index + 1}...` });
    try {
      applyRefineResult(await refineRedoKeyframe(keyframe.id));
      onstatus({ detail: 'Refinement redone.' });
    } catch (e) {
      onstatus({ detail: `Redo failed: ${e.message}` });
    }
  }

  async function handleRefineNewSeed() {
    if (refineHistory.length < 2) return;
    const lastPrompt = refineHistory[refineHistory.length - 1].prompt;
    onstatus({ detail: `Re-rolling keyframe ${index + 1} with new seed...` });
    try {
      // Undo the last step, then re-refine with same prompt but new seed
      await refineUndoKeyframe(keyframe.id);
      const result = await refineKeyframe(keyframe.id, lastPrompt, keyframe.negative_prompt);
      keyframe.status = 'rendering';
      onstatus({ detail: `Keyframe ${index + 1} refining with new seed...` });
    } catch (e) {
      onstatus({ detail: `New seed failed: ${e.message}` });
    }
  }

  function cancelRefine() {
    refining = false;
  }

  function handleRefineKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submitRefine();
    } else if (e.key === 'Escape') {
      cancelRefine();
    }
  }

  async function handleDuplicate() {
    onstatus({ detail: `Duplicating keyframe ${index + 1}...` });
    try {
      const data = await duplicateKeyframe(keyframe.id);
      if (onduplicate) onduplicate({ detail: { keyframes: data.keyframes, transitions: data.transitions } });
      onstatus({ detail: `Keyframe ${index + 1} duplicated.` });
    } catch (e) {
      onstatus({ detail: `Duplicate failed: ${e.message}` });
    }
  }

  async function handleModelChange(e) {
    const newModel = e.target.value;
    keyframe.model = newModel;
    try {
      await updateKeyframe(keyframe.id, { model: newModel });
      onstatus({ detail: `Keyframe ${index + 1} model set to ${T2I_MODELS.find(m => m.id === newModel)?.label}. Re-render to apply.` });
    } catch (err) {
      onstatus({ detail: `Failed: ${err.message}` });
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
      const data = await deleteKeyframe(keyframe.id);
      ondelete({ detail: { id: keyframe.id, transitions: data.transitions } });
      onstatus({ detail: `Deleted keyframe ${index + 1}` });
    } catch (e) {
      onstatus({ detail: `Delete failed: ${e.message}` });
    }
  }

  function autoFocus(node) {
    node.focus();
    node.setSelectionRange(node.value.length, node.value.length);
  }

  function focusOverlay(node) {
    node.focus();
  }

  async function handleFullscreenKeydown(e) {
    if (e.key === 'Escape') {
      fullscreen = false;
    } else if (e.key === 'c' && (e.ctrlKey || e.metaKey) && imageUrl) {
      e.preventDefault();
      try {
        const resp = await fetch(imageUrl);
        const blob = await resp.blob();
        await navigator.clipboard.write([
          new ClipboardItem({ [blob.type]: blob })
        ]);
        onstatus({ detail: `Keyframe ${index + 1} image copied to clipboard.` });
      } catch (err) {
        onstatus({ detail: `Copy failed: ${err.message}` });
      }
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

  let imageAreaRef = $state(null);
  let hovered = $state(false);

  function handleImageAreaEnter() {
    hovered = true;
    imageAreaRef?.focus();
  }

  function handleImageAreaLeave() {
    hovered = false;
  }

  async function handleImageAreaKeydown(e) {
    if (e.key === 'c' && (e.ctrlKey || e.metaKey) && imageUrl) {
      e.preventDefault();
      try {
        const resp = await fetch(imageUrl);
        const blob = await resp.blob();
        await navigator.clipboard.write([
          new ClipboardItem({ [blob.type]: blob })
        ]);
        onstatus({ detail: `Keyframe ${index + 1} image copied to clipboard.` });
      } catch (err) {
        onstatus({ detail: `Copy failed: ${err.message}` });
      }
    }
  }

  async function handleImageAreaPaste(e) {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        e.preventDefault();
        const blob = item.getAsFile();
        if (!blob) continue;
        onstatus({ detail: `Pasting image into keyframe ${index + 1}...` });
        try {
          const result = await uploadKeyframeImage(keyframe.id, blob);
          keyframe.image_filename = result.image_filename;
          keyframe.seed = result.seed;
          keyframe.status = result.status;
          onstatus({ detail: `Keyframe ${index + 1} replaced from clipboard.` });
        } catch (err) {
          onstatus({ detail: `Paste failed: ${err.message}` });
        }
        return;
      }
    }
  }
</script>

<div class="card" class:error={keyframe.status === 'error'}>
  <div class="card-header">
    <span class="position">{index + 1}</span>
    <span class="status-badge" class:pending={keyframe.status === 'pending'}
          class:rendering={keyframe.status === 'rendering'}
          class:done={keyframe.status === 'done'}
          class:error={keyframe.status === 'error'}>
      {keyframe.status}
    </span>
    <select class="model-select" value={keyframe.model || 'hidream'}
            onchange={handleModelChange}>
      {#each T2I_MODELS as m}
        <option value={m.id}>{m.label}</option>
      {/each}
    </select>
  </div>

  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="image-area" class:hovered
       bind:this={imageAreaRef}
       tabindex="-1"
       onclick={() => imageUrl && (fullscreen = true)}
       onmouseenter={handleImageAreaEnter}
       onmouseleave={handleImageAreaLeave}
       onkeydown={handleImageAreaKeydown}
       onpaste={handleImageAreaPaste}>
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
      <p class="prompt-text clickable" class:empty={!keyframe.prompt} onclick={startEdit}>{keyframe.prompt || 'Click to enter prompt...'}</p>
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

    {#if refining}
      <div class="refine-edit">
        <label class="refine-label">Refine image (img2img)</label>

        {#if refineHistory.length > 0}
          <div class="refine-history">
            {#each refineHistory as entry, i}
              <div class="refine-history-entry" class:current={i === refineIndex} class:future={i > refineIndex}>
                <span class="refine-history-step">{i === 0 ? 'Original' : `Refine ${i}`}</span>
                <span class="refine-history-model">{entry.model}</span>
                <p class="refine-history-prompt">{entry.prompt}</p>
              </div>
            {/each}
          </div>
          <div class="refine-actions">
            <button class="btn-cancel" onclick={handleRefineUndo} disabled={!canRefineUndo}>
              <Undo2 size={14} /> Undo
            </button>
            <button class="btn-cancel" onclick={handleRefineRedo} disabled={!canRefineRedo}>
              <Redo2 size={14} /> Redo
            </button>
            <button class="btn-cancel" onclick={handleRefineNewSeed}
                    disabled={refineHistory.length < 2 || keyframe.status === 'rendering'}>
              <RefreshCw size={14} /> New Seed
            </button>
          </div>
        {/if}

        <textarea
          bind:value={refinePrompt}
          onkeydown={handleRefineKeydown}
          rows="2"
          class="edit-textarea"
          placeholder="e.g. Add more clouds, change the lighting to golden hour..."
          disabled={refineLoading}
          use:autoFocus
        ></textarea>
        <div class="edit-actions">
          <button class="btn-save refine-btn" onclick={submitRefine} disabled={refineLoading || !refinePrompt.trim()}>
            <Paintbrush size={14} /> {refineLoading ? 'Refining...' : 'Refine Image'}
          </button>
          <button class="btn-cancel" onclick={cancelRefine} disabled={refineLoading}>
            <X size={14} /> Close
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
    <button class="btn-icon" onclick={startRewrite} title="Rewrite prompt with AI">
      <Wand2 size={16} />
    </button>
    <button class="btn-icon" onclick={startRefine} title="Refine image (img2img)"
            disabled={!keyframe.image_filename || keyframe.status === 'rendering'}>
      <Paintbrush size={16} />
    </button>
    <button class="btn-icon" class:btn-active={!!keyframe.negative_prompt}
            onclick={startEditNeg} title="Negative prompt">
      <ThumbsDown size={16} />
    </button>
    <button class="btn-icon" onclick={handleDuplicate} title="Duplicate keyframe">
      <Copy size={16} />
    </button>
    <button class="btn-icon btn-danger" onclick={handleDelete} title="Delete">
      <Trash2 size={16} />
    </button>
  </div>
</div>

{#if fullscreen && imageUrl}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="fullscreen-overlay" onclick={() => fullscreen = false}
       onkeydown={handleFullscreenKeydown} onpaste={handleFullscreenPaste}
       tabindex="-1" use:focusOverlay>
    <img src={imageUrl} alt="Keyframe {index + 1} full size" />
    <div class="fullscreen-hint">Ctrl+C copy / Ctrl+V paste / Esc close</div>
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

  .model-select {
    margin-left: auto;
    font-family: inherit;
    font-size: 11px;
    color: var(--text-dim);
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 2px 6px;
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


  .image-area {
    position: relative;
    aspect-ratio: 16 / 9;
    background: var(--bg);
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    cursor: pointer;
  }

  .image-area:focus { outline: none; }

  .image-area.hovered::after {
    content: 'Ctrl+C / Ctrl+V';
    position: absolute;
    bottom: 6px;
    right: 8px;
    font-size: 11px;
    color: rgba(255, 255, 255, 0.7);
    background: rgba(0, 0, 0, 0.5);
    padding: 2px 8px;
    border-radius: 4px;
    pointer-events: none;
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

  .prompt-text.empty {
    font-style: italic;
    color: var(--text-muted);
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

  .refine-edit {
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid var(--border);
  }

  .refine-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--success);
    display: block;
    margin-bottom: 4px;
  }

  .refine-history {
    max-height: 140px;
    overflow-y: auto;
    margin-bottom: 8px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .refine-history-entry {
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 6px 10px;
  }

  .refine-history-entry.current {
    border-color: var(--success);
  }

  .refine-history-entry.future {
    opacity: 0.45;
  }

  .refine-history-step {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-muted);
    margin-right: 6px;
  }

  .refine-history-model {
    font-size: 10px;
    color: var(--success);
    background: rgba(34, 197, 94, 0.1);
    padding: 1px 5px;
    border-radius: 3px;
  }

  .refine-history-prompt {
    font-size: 12px;
    color: var(--text-dim);
    line-height: 1.3;
    margin-top: 2px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .refine-actions {
    display: flex;
    gap: 6px;
    margin-bottom: 8px;
  }

  .refine-btn {
    background: var(--success);
  }

  .refine-btn:hover:not(:disabled) {
    filter: brightness(1.1);
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
    flex-wrap: wrap;
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
