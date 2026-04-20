<script>
  import { flip } from 'svelte/animate';
  import { RefreshCw, Pencil, Trash2, Check, X, ThumbsDown, RotateCcw, Zap, ArrowRight } from 'lucide-svelte';
  import { renderTransition, rerenderTransition, updateTransition,
           getTransitionStatus, setTransitionActiveIndex, resetTransitions,
           autoCreateTransitions, lockTransitions } from '../lib/api.js';

  let { transitions = $bindable([]), keyframes = [], projectId = '',
        locked = false, onstatus, onreset, onlocktransitions } = $props();

  let activeIndex = $state(-1);
  let initialized = $state(false);
  let autoCreating = $state(false);
  let locking = $state(false);

  $effect(() => {
    if (initialized || transitions.length === 0) return;
    initialized = true;
    const firstPending = transitions.findIndex(t => t.status === 'pending');
    if (firstPending === -1) {
      activeIndex = transitions.length - 1;
    } else if (firstPending === 0) {
      activeIndex = 0;
    } else {
      activeIndex = firstPending - 1;
    }
  });

  let allDone = $derived(transitions.length > 0 && transitions.every(t => t.status === 'done'));

  function getKeyframe(id) {
    return keyframes.find(kf => kf.id === id);
  }

  function imageUrl(kf) {
    if (!kf?.image_filename || !projectId) return null;
    return `/api/projects/${projectId}/images/${kf.image_filename}?v=${kf.seed || 0}`;
  }

  function videoUrl(tr) {
    if (!tr?.video_filename || !projectId) return null;
    return `/api/projects/${projectId}/videos/${tr.video_filename}?v=${tr.seed || 0}`;
  }

  // ── Per-card state (tracked by transition id) ──
  let editing = $state({});
  let editPrompts = $state({});
  let editingNeg = $state({});
  let editNegPrompts = $state({});
  let polling = $state({});

  function startEdit(tr) {
    editPrompts[tr.id] = tr.prompt;
    editing[tr.id] = true;
  }

  async function saveEdit(tr) {
    try {
      await updateTransition(tr.id, { prompt: editPrompts[tr.id] });
      tr.prompt = editPrompts[tr.id];
      editing[tr.id] = false;
      onstatus({ detail: `Updated transition ${tr.position + 1} prompt` });
    } catch (e) {
      onstatus({ detail: `Update failed: ${e.message}` });
    }
  }

  function cancelEdit(tr) { editing[tr.id] = false; }

  function startEditNeg(tr) {
    editNegPrompts[tr.id] = tr.negative_prompt || '';
    editingNeg[tr.id] = true;
  }

  async function saveNegEdit(tr) {
    try {
      await updateTransition(tr.id, { negative_prompt: editNegPrompts[tr.id] });
      tr.negative_prompt = editNegPrompts[tr.id];
      editingNeg[tr.id] = false;
      onstatus({ detail: `Updated transition ${tr.position + 1} negative prompt` });
    } catch (e) {
      onstatus({ detail: `Update failed: ${e.message}` });
    }
  }

  function cancelNegEdit(tr) { editingNeg[tr.id] = false; }

  async function handleRender(tr) {
    onstatus({ detail: `Rendering transition ${tr.position + 1}...` });
    tr.status = 'rendering';
    try {
      await renderTransition(tr.id);
      pollStatus(tr);
    } catch (e) {
      onstatus({ detail: `Render failed: ${e.message}` });
    }
  }

  async function handleRerender(tr) {
    onstatus({ detail: `Re-rendering transition ${tr.position + 1}...` });
    tr.status = 'rendering';
    try {
      await rerenderTransition(tr.id);
      pollStatus(tr);
    } catch (e) {
      onstatus({ detail: `Re-render failed: ${e.message}` });
    }
  }

  async function pollStatus(tr) {
    if (polling[tr.id]) return;
    polling[tr.id] = true;
    while (tr.status === 'rendering') {
      await new Promise(r => setTimeout(r, 3000));
      try {
        const status = await getTransitionStatus(tr.id);
        tr.status = status.status;
        tr.error_message = status.error_message;
        if (status.seed != null) tr.seed = status.seed;
        if (status.video_url) tr.video_filename = status.video_url.split('/').pop();
      } catch { break; }
    }
    polling[tr.id] = false;
  }

  // Start polling for any that are already rendering on load
  $effect(() => {
    for (const tr of transitions) {
      if (tr.status === 'rendering' && !polling[tr.id]) {
        pollStatus(tr);
      }
    }
  });

  async function handleApprove() {
    const nextIndex = activeIndex + 1;
    if (nextIndex < transitions.length) {
      activeIndex = nextIndex;
      setTransitionActiveIndex(activeIndex);
      const next = transitions[nextIndex];
      if (next.status === 'pending') {
        onstatus({ detail: `Approved #${activeIndex}. Rendering transition #${nextIndex + 1}...` });
        handleRender(next);
      } else {
        onstatus({ detail: `Approved #${activeIndex}. Reviewing transition #${nextIndex + 1}...` });
      }
    } else {
      onstatus({ detail: 'All transitions approved!' });
      activeIndex = transitions.length;
      setTransitionActiveIndex(activeIndex);
    }
  }

  async function handleReset() {
    if (!confirm('Reset all transitions? All rendered videos will be deleted and descriptions regenerated.')) return;
    onstatus({ detail: 'Resetting transitions...' });
    try {
      const data = await resetTransitions();
      if (onreset) onreset({ detail: data.project });
      onstatus({ detail: 'Transitions reset.' });
      initialized = false;
    } catch (e) {
      onstatus({ detail: `Reset failed: ${e.message}` });
    }
  }

  async function handleAutoCreate() {
    if (!confirm('Render all remaining transitions automatically?')) return;
    autoCreating = true;
    onstatus({ detail: 'Auto-creating all transitions...' });
    try {
      const data = await autoCreateTransitions();
      if (onreset) onreset({ detail: data.project });
      onstatus({ detail: `Auto-created ${data.rendered} transitions.` });
      initialized = false;
    } catch (e) {
      onstatus({ detail: `Auto-create failed: ${e.message}` });
    } finally {
      autoCreating = false;
    }
  }

  async function handleGoToNarration() {
    locking = true;
    onstatus({ detail: 'Locking transitions and generating narration...' });
    try {
      const data = await lockTransitions();
      if (onlocktransitions) onlocktransitions({ detail: data.project });
      onstatus({ detail: 'Transitions locked. Proceed to Narration.' });
    } catch (e) {
      onstatus({ detail: `Failed: ${e.message}` });
    } finally {
      locking = false;
    }
  }

  function autoFocus(node) {
    node.focus();
    node.setSelectionRange(node.value.length, node.value.length);
  }

  function editKeydown(e, tr, save, cancel) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); save(tr); }
    else if (e.key === 'Escape') { cancel(tr); }
  }
</script>

{#if transitions.length > 0}
  {#if !locked}
    <div class="toolbar">
      <button class="toolbar-btn" onclick={handleReset}>
        <RotateCcw size={14} /> Reset
      </button>
      <button class="toolbar-btn" onclick={handleAutoCreate} disabled={autoCreating || allDone}>
        <Zap size={14} /> {autoCreating ? 'Creating...' : 'Auto Create'}
      </button>
    </div>
  {/if}

  <div class="transitions">
    {#each transitions as tr, i (tr.id)}
      {@const fromKf = getKeyframe(tr.from_keyframe_id)}
      {@const toKf = getKeyframe(tr.to_keyframe_id)}
      {@const isActive = i === activeIndex}
      {@const isEditing = editing[tr.id]}
      {@const isEditingNeg = editingNeg[tr.id]}

      <div class="transition-card" class:active={isActive}>
        <div class="card-header">
          <span class="position">{i + 1}</span>
          <span class="label">Keyframe {tr.position + 1} → {tr.position + 2}</span>
          <span class="status-badge" class:pending={tr.status === 'pending'}
                class:rendering={tr.status === 'rendering'}
                class:done={tr.status === 'done'}
                class:error={tr.status === 'error'}>
            {tr.status}
          </span>
        </div>

        <div class="keyframe-pair">
          <div class="kf-thumb">
            {#if imageUrl(fromKf)}
              <img src={imageUrl(fromKf)} alt="From" />
            {:else}
              <div class="kf-placeholder">?</div>
            {/if}
          </div>
          <div class="arrow">→</div>
          {#if tr.status === 'done' && videoUrl(tr)}
            <!-- svelte-ignore a11y_media_has_caption -->
            <video class="transition-video" src={videoUrl(tr)} controls loop autoplay muted></video>
          {:else if tr.status === 'rendering'}
            <div class="render-placeholder">
              <div class="spinner"></div>
              <span>Rendering...</span>
            </div>
          {:else if tr.status === 'error'}
            <div class="render-placeholder error">
              <span>Error</span>
              <small>{tr.error_message || 'Unknown'}</small>
            </div>
          {:else}
            <div class="render-placeholder">Pending</div>
          {/if}
          <div class="arrow">→</div>
          <div class="kf-thumb">
            {#if imageUrl(toKf)}
              <img src={imageUrl(toKf)} alt="To" />
            {:else}
              <div class="kf-placeholder">?</div>
            {/if}
          </div>
        </div>

        <div class="card-body">
          {#if isEditing}
            <textarea bind:value={editPrompts[tr.id]}
                      onkeydown={(e) => editKeydown(e, tr, saveEdit, cancelEdit)}
                      rows="4" class="edit-textarea" use:autoFocus></textarea>
            <div class="edit-actions">
              <button class="btn-save" onclick={() => saveEdit(tr)}><Check size={14} /> Save</button>
              <button class="btn-cancel" onclick={() => cancelEdit(tr)}><X size={14} /> Cancel</button>
            </div>
          {:else}
            <p class="prompt-text">{tr.prompt}</p>
          {/if}

          {#if isEditingNeg}
            <div class="neg-edit">
              <label class="neg-label">Negative prompt</label>
              <textarea bind:value={editNegPrompts[tr.id]}
                        onkeydown={(e) => editKeydown(e, tr, saveNegEdit, cancelNegEdit)}
                        rows="2" class="edit-textarea" placeholder="Things to avoid..."
                        use:autoFocus></textarea>
              <div class="edit-actions">
                <button class="btn-save" onclick={() => saveNegEdit(tr)}><Check size={14} /> Save</button>
                <button class="btn-cancel" onclick={() => cancelNegEdit(tr)}><X size={14} /> Cancel</button>
              </div>
            </div>
          {:else if tr.negative_prompt}
            <p class="neg-display"><span class="neg-label">Negative:</span> {tr.negative_prompt}</p>
          {/if}
        </div>

        <div class="card-actions">
          <button class="btn-icon" onclick={() => handleRerender(tr)} title="Re-render"
                  disabled={tr.status === 'rendering'}>
            <RefreshCw size={16} />
          </button>
          <button class="btn-icon" onclick={() => startEdit(tr)} title="Edit prompt">
            <Pencil size={16} />
          </button>
          <button class="btn-icon" class:btn-active={!!tr.negative_prompt}
                  onclick={() => startEditNeg(tr)} title="Negative prompt">
            <ThumbsDown size={16} />
          </button>
          {#if isActive && tr.status === 'done' && !isEditing && !isEditingNeg}
            <button class="btn-approve" onclick={handleApprove} title="Approve and render next">
              <Check size={16} /> Approve
            </button>
          {/if}
        </div>
      </div>
    {/each}
  </div>

  {#if allDone && !locked}
    <div class="all-done">
      <span>All transitions approved!</span>
      <button class="go-btn" onclick={handleGoToNarration} disabled={locking}>
        {locking ? 'Generating narration...' : 'Go to Narration'} <ArrowRight size={16} />
      </button>
    </div>
  {/if}
{:else}
  <div class="empty">
    <p>No transitions yet. Approve all keyframes first.</p>
  </div>
{/if}

<style>
  .toolbar {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-bottom: 12px;
  }

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

  .transitions {
    display: flex;
    flex-direction: column;
    gap: 16px;
    margin-bottom: 24px;
  }

  .transition-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }

  .transition-card.active {
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

  .label {
    font-size: 13px;
    color: var(--text-muted);
  }

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

  .keyframe-pair {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px;
    background: var(--bg);
  }

  .kf-thumb {
    width: 120px;
    flex-shrink: 0;
    aspect-ratio: 16 / 9;
    border-radius: var(--radius);
    overflow: hidden;
    background: var(--bg-card);
  }

  .kf-thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .kf-placeholder {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
  }

  .arrow {
    color: var(--text-muted);
    font-size: 20px;
    flex-shrink: 0;
  }

  .transition-video {
    flex: 1;
    min-width: 0;
    max-height: 200px;
    border-radius: var(--radius);
    background: #000;
  }

  .render-placeholder {
    flex: 1;
    min-height: 100px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    color: var(--text-muted);
    font-size: 13px;
  }

  .render-placeholder.error { color: var(--error); }
  .render-placeholder small { font-size: 11px; max-width: 200px; text-align: center; }

  .spinner {
    width: 24px;
    height: 24px;
    border: 3px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  .card-body {
    padding: 12px 14px;
  }

  .prompt-text {
    font-size: 13px;
    color: var(--text-dim);
    line-height: 1.5;
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

  .neg-display {
    margin-top: 8px;
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.4;
  }

  .neg-display .neg-label { display: inline; font-size: 12px; margin: 0; }

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

  .btn-active { color: var(--warning); }

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
    justify-content: space-between;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 20px 24px;
    margin-bottom: 24px;
  }

  .go-btn {
    background: var(--accent);
    color: white;
    font-weight: 500;
    padding: 10px 24px;
    font-size: 15px;
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }

  .go-btn:hover:not(:disabled) { background: var(--accent-hover); }

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
