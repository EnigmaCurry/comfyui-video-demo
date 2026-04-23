<script>
  import { dndzone } from 'svelte-dnd-action';
  import { flip } from 'svelte/animate';
  import { RefreshCw, Pencil, Trash2, Check, X, ThumbsDown, Wand2, Upload, Plus,
           ChevronDown, RotateCcw } from 'lucide-svelte';
  import {
    listSequences, createSequence, updateSequence, deleteSequence, activateSequence,
    seqAddKeyframe, seqUpdateKeyframe, seqDeleteKeyframe, seqReorderKeyframes,
    seqKeyframeStatus, seqRenderKeyframe, seqRerenderKeyframe, seqRewriteKeyframe,
    seqUploadKeyframe, seqSyncTransitions, seqTransitionStatus, seqUpdateTransition,
    seqRenderTransition, seqRerenderTransition, T2I_MODELS,
  } from '../lib/api.js';

  let { project = $bindable(), onstatus } = $props();

  let projectId = $derived(project?.id || '');
  let sequences = $state([]);
  let activeSeqId = $state(null);
  let activeSeq = $derived(sequences.find(s => s.id === activeSeqId) || null);
  let keyframes = $derived(activeSeq?.keyframes || []);
  let transitions = $derived(activeSeq?.transitions || []);

  // ── Sequence selector state ──
  let showSeqMenu = $state(false);
  let renamingSeq = $state(false);
  let renameValue = $state('');
  let creatingSeq = $state(false);
  let createName = $state('');

  // ── Per-keyframe edit state ──
  let editing = $state({});
  let editPrompts = $state({});
  let editingNeg = $state({});
  let editNegPrompts = $state({});
  let rewriting = $state({});
  let rewriteInstructions = $state({});
  let rewriteLoading = $state({});
  let polling = $state({});

  // ── Per-transition edit state ──
  let trEditing = $state({});
  let trEditPrompts = $state({});
  let trPolling = $state({});

  const flipDurationMs = 200;

  // ── Init ──
  async function init() {
    if (!projectId) return;
    try {
      const data = await listSequences();
      sequences = data.sequences || [];
      activeSeqId = data.active_sequence_id;
      // Start polling for any rendering items
      if (activeSeq) {
        for (const kf of activeSeq.keyframes) {
          if (kf.status === 'rendering') pollKeyframe(kf);
        }
        for (const tr of activeSeq.transitions) {
          if (tr.status === 'rendering') pollTransition(tr);
        }
      }
    } catch (e) {
      onstatus?.({ detail: `Failed to load sequences: ${e.message}` });
    }
  }

  $effect(() => { projectId; init(); });

  // ── Sequence CRUD ──
  async function handleCreateSequence() {
    const name = createName.trim() || 'Untitled Sequence';
    try {
      const data = await createSequence(name);
      sequences = [...sequences, data.sequence];
      activeSeqId = data.sequence.id;
      creatingSeq = false;
      createName = '';
      onstatus?.({ detail: `Created sequence "${name}".` });
    } catch (e) {
      onstatus?.({ detail: `Create failed: ${e.message}` });
    }
  }

  async function handleSelectSequence(id) {
    activeSeqId = id;
    showSeqMenu = false;
    try {
      await activateSequence(id);
    } catch {}
  }

  async function handleRenameSequence() {
    if (!activeSeq) return;
    const name = renameValue.trim() || 'Untitled Sequence';
    try {
      await updateSequence(activeSeqId, { name });
      activeSeq.name = name;
      renamingSeq = false;
      onstatus?.({ detail: `Renamed to "${name}".` });
    } catch (e) {
      onstatus?.({ detail: `Rename failed: ${e.message}` });
    }
  }

  async function handleDeleteSequence() {
    if (!activeSeq) return;
    if (!confirm(`Delete sequence "${activeSeq.name}"?`)) return;
    try {
      const data = await deleteSequence(activeSeqId);
      sequences = sequences.filter(s => s.id !== activeSeqId);
      activeSeqId = sequences[0]?.id || null;
      onstatus?.({ detail: 'Sequence deleted.' });
    } catch (e) {
      onstatus?.({ detail: `Delete failed: ${e.message}` });
    }
  }

  // ── Keyframe operations ──
  async function handleAddKeyframe() {
    if (!activeSeqId) return;
    try {
      const data = await seqAddKeyframe(activeSeqId);
      replaceSeq(data.sequence);
      onstatus?.({ detail: `Added keyframe ${data.sequence.keyframes.length}.` });
    } catch (e) {
      onstatus?.({ detail: `Add failed: ${e.message}` });
    }
  }

  async function handleDeleteKeyframe(kfId) {
    if (!activeSeqId) return;
    try {
      const data = await seqDeleteKeyframe(activeSeqId, kfId);
      replaceSeq(data.sequence);
      onstatus?.({ detail: 'Keyframe deleted.' });
    } catch (e) {
      onstatus?.({ detail: `Delete failed: ${e.message}` });
    }
  }

  function handleDndConsider(e) {
    if (activeSeq) activeSeq.keyframes = e.detail.items;
  }

  async function handleDndFinalize(e) {
    if (!activeSeq) return;
    activeSeq.keyframes = e.detail.items;
    try {
      const ids = activeSeq.keyframes.map(kf => kf.id);
      const data = await seqReorderKeyframes(activeSeqId, ids);
      replaceSeq(data.sequence);
    } catch (e) {
      onstatus?.({ detail: `Reorder failed: ${e.message}` });
    }
  }

  // ── Keyframe editing ──
  function startEditKf(kf) { editPrompts[kf.id] = kf.prompt; editing[kf.id] = true; }

  async function saveEditKf(kf) {
    try {
      await seqUpdateKeyframe(activeSeqId, kf.id, { prompt: editPrompts[kf.id] });
      kf.prompt = editPrompts[kf.id];
      editing[kf.id] = false;
      onstatus?.({ detail: 'Prompt updated.' });
    } catch (e) {
      onstatus?.({ detail: `Update failed: ${e.message}` });
    }
  }

  function cancelEditKf(kf) { editing[kf.id] = false; }

  function startEditNeg(kf) { editNegPrompts[kf.id] = kf.negative_prompt || ''; editingNeg[kf.id] = true; }

  async function saveNegEdit(kf) {
    try {
      await seqUpdateKeyframe(activeSeqId, kf.id, { negative_prompt: editNegPrompts[kf.id] });
      kf.negative_prompt = editNegPrompts[kf.id];
      editingNeg[kf.id] = false;
      onstatus?.({ detail: 'Negative prompt updated.' });
    } catch (e) {
      onstatus?.({ detail: `Update failed: ${e.message}` });
    }
  }

  function cancelNegEdit(kf) { editingNeg[kf.id] = false; }

  function startRewrite(kf) { rewriteInstructions[kf.id] = ''; rewriting[kf.id] = true; }

  async function submitRewrite(kf) {
    const inst = (rewriteInstructions[kf.id] || '').trim();
    if (!inst) return;
    rewriteLoading[kf.id] = true;
    try {
      const result = await seqRewriteKeyframe(activeSeqId, kf.id, inst);
      kf.prompt = result.prompt;
      kf.status = 'rendering';
      rewriting[kf.id] = false;
      pollKeyframe(kf);
      onstatus?.({ detail: 'Rewriting and rendering...' });
    } catch (e) {
      onstatus?.({ detail: `Rewrite failed: ${e.message}` });
    } finally {
      rewriteLoading[kf.id] = false;
    }
  }

  function cancelRewrite(kf) { rewriting[kf.id] = false; }

  // ── Keyframe render ──
  async function handleRenderKf(kf) {
    onstatus?.({ detail: `Rendering keyframe...` });
    kf.status = 'rendering';
    try {
      await seqRenderKeyframe(activeSeqId, kf.id);
      pollKeyframe(kf);
    } catch (e) {
      onstatus?.({ detail: `Render failed: ${e.message}` });
    }
  }

  async function handleRerenderKf(kf) {
    onstatus?.({ detail: `Re-rendering keyframe...` });
    kf.status = 'rendering';
    try {
      await seqRerenderKeyframe(activeSeqId, kf.id);
      pollKeyframe(kf);
    } catch (e) {
      onstatus?.({ detail: `Re-render failed: ${e.message}` });
    }
  }

  async function pollKeyframe(kf) {
    if (polling[kf.id]) return;
    polling[kf.id] = true;
    while (kf.status === 'rendering') {
      await new Promise(r => setTimeout(r, 2000));
      try {
        const status = await seqKeyframeStatus(activeSeqId, kf.id);
        kf.status = status.status;
        kf.error_message = status.error_message;
        if (status.seed != null) kf.seed = status.seed;
        if (status.image_url) kf.image_filename = status.image_url.split('/').pop();
      } catch { break; }
    }
    polling[kf.id] = false;
  }

  async function handleModelChange(kf, e) {
    kf.model = e.target.value;
    try {
      await seqUpdateKeyframe(activeSeqId, kf.id, { model: kf.model });
      onstatus?.({ detail: `Model changed. Re-render to apply.` });
    } catch (e) {
      onstatus?.({ detail: `Failed: ${e.message}` });
    }
  }

  let fileInputs = $state({});

  async function handleUpload(kf, e) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const result = await seqUploadKeyframe(activeSeqId, kf.id, file);
      kf.image_filename = result.image_filename;
      kf.seed = result.seed;
      kf.status = result.status;
      onstatus?.({ detail: 'Image uploaded.' });
    } catch (err) {
      onstatus?.({ detail: `Upload failed: ${err.message}` });
    }
    e.target.value = '';
  }

  // ── Transition operations ──
  async function handleSyncTransitions() {
    if (!activeSeqId) return;
    onstatus?.({ detail: 'Syncing transitions...' });
    try {
      const data = await seqSyncTransitions(activeSeqId);
      replaceSeq(data.sequence);
      onstatus?.({ detail: 'Transitions synced.' });
    } catch (e) {
      onstatus?.({ detail: `Sync failed: ${e.message}` });
    }
  }

  function startEditTr(tr) { trEditPrompts[tr.id] = tr.prompt; trEditing[tr.id] = true; }

  async function saveEditTr(tr) {
    try {
      await seqUpdateTransition(activeSeqId, tr.id, { prompt: trEditPrompts[tr.id] });
      tr.prompt = trEditPrompts[tr.id];
      trEditing[tr.id] = false;
      onstatus?.({ detail: 'Transition prompt updated. Re-rendering...' });
      handleRerenderTr(tr);
    } catch (e) {
      onstatus?.({ detail: `Update failed: ${e.message}` });
    }
  }

  function cancelEditTr(tr) { trEditing[tr.id] = false; }

  async function handleRenderTr(tr) {
    onstatus?.({ detail: `Rendering transition...` });
    tr.status = 'rendering';
    try {
      await seqRenderTransition(activeSeqId, tr.id);
      pollTransition(tr);
    } catch (e) {
      onstatus?.({ detail: `Render failed: ${e.message}` });
    }
  }

  async function handleRerenderTr(tr) {
    onstatus?.({ detail: `Re-rendering transition...` });
    tr.status = 'rendering';
    try {
      await seqRerenderTransition(activeSeqId, tr.id);
      pollTransition(tr);
    } catch (e) {
      onstatus?.({ detail: `Re-render failed: ${e.message}` });
    }
  }

  async function pollTransition(tr) {
    if (trPolling[tr.id]) return;
    trPolling[tr.id] = true;
    while (tr.status === 'rendering') {
      await new Promise(r => setTimeout(r, 3000));
      try {
        const status = await seqTransitionStatus(activeSeqId, tr.id);
        tr.status = status.status;
        tr.error_message = status.error_message;
        if (status.seed != null) tr.seed = status.seed;
        if (status.video_url) tr.video_filename = status.video_url.split('/').pop();
      } catch { break; }
    }
    trPolling[tr.id] = false;
  }

  // ── Helpers ──
  function replaceSeq(newSeq) {
    const idx = sequences.findIndex(s => s.id === newSeq.id);
    if (idx >= 0) sequences[idx] = newSeq;
    else sequences = [...sequences, newSeq];
  }

  function kfImageUrl(kf) {
    if (!kf?.image_filename || !projectId) return null;
    return `/api/projects/${projectId}/images/${kf.image_filename}?v=${kf.seed || 0}`;
  }

  function trVideoUrl(tr) {
    if (!tr?.video_filename || !projectId) return null;
    return `/api/projects/${projectId}/videos/${tr.video_filename}?v=${tr.seed || 0}`;
  }

  function getKeyframe(id) {
    return keyframes.find(kf => kf.id === id);
  }

  function autoFocus(node) {
    node.focus();
    node.setSelectionRange(node.value.length, node.value.length);
  }

  function editKeydown(e, item, save, cancel) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); save(item); }
    else if (e.key === 'Escape') { cancel(item); }
  }
</script>

<!-- Sequence selector bar -->
<div class="seq-bar">
  <div class="seq-selector">
    {#if sequences.length === 0}
      <button class="seq-create-btn" onclick={() => { creatingSeq = true; createName = ''; }}>
        <Plus size={14} /> New Sequence
      </button>
    {:else}
      <div class="seq-dropdown-wrap">
        {#if renamingSeq}
          <input class="seq-rename-input" bind:value={renameValue}
                 onkeydown={(e) => { if (e.key === 'Enter') handleRenameSequence(); else if (e.key === 'Escape') renamingSeq = false; }}
                 onblur={handleRenameSequence} use:autoFocus />
        {:else}
          <button class="seq-dropdown-btn" onclick={() => showSeqMenu = !showSeqMenu}>
            {activeSeq?.name || 'Select Sequence'} <ChevronDown size={14} />
          </button>
        {/if}
        {#if showSeqMenu}
          <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
          <div class="seq-menu-overlay" onclick={() => showSeqMenu = false}></div>
          <div class="seq-menu">
            {#each sequences as seq (seq.id)}
              <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
              <div class="seq-menu-item" class:active={seq.id === activeSeqId}
                   onclick={() => handleSelectSequence(seq.id)}>
                {seq.name}
              </div>
            {/each}
            <div class="seq-menu-divider"></div>
            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
            <div class="seq-menu-item create" onclick={() => { showSeqMenu = false; creatingSeq = true; createName = ''; }}>
              <Plus size={14} /> New Sequence
            </div>
          </div>
        {/if}
      </div>
      <button class="seq-action-btn" onclick={() => { renameValue = activeSeq?.name || ''; renamingSeq = true; }}
              title="Rename">
        <Pencil size={14} />
      </button>
      <button class="seq-action-btn danger" onclick={handleDeleteSequence} title="Delete sequence">
        <Trash2 size={14} />
      </button>
      <button class="seq-create-btn small" onclick={() => { creatingSeq = true; createName = ''; }}>
        <Plus size={14} />
      </button>
    {/if}
  </div>
</div>

<!-- Create sequence dialog -->
{#if creatingSeq}
  <div class="create-seq-bar">
    <input class="create-seq-input" bind:value={createName} placeholder="Sequence name..."
           onkeydown={(e) => { if (e.key === 'Enter') handleCreateSequence(); else if (e.key === 'Escape') creatingSeq = false; }}
           use:autoFocus />
    <button class="btn-save" onclick={handleCreateSequence}><Check size={14} /> Create</button>
    <button class="btn-cancel" onclick={() => creatingSeq = false}><X size={14} /> Cancel</button>
  </div>
{/if}

<!-- Main split layout -->
{#if activeSeq}
  <div class="split-layout">
    <!-- LEFT: Keyframes -->
    <div class="left-panel">
      <div class="panel-header">
        <h3>Keyframes</h3>
        <button class="toolbar-btn" onclick={handleAddKeyframe}><Plus size={14} /> Add</button>
        {#if keyframes.some(kf => kf.status === 'done')}
          <button class="toolbar-btn" onclick={handleSyncTransitions}>
            <RotateCcw size={14} /> Sync Transitions
          </button>
        {/if}
      </div>

      {#if keyframes.length > 0}
        <div class="kf-list"
             use:dndzone={{ items: keyframes, flipDurationMs, type: 'seq-keyframes' }}
             onconsider={handleDndConsider}
             onfinalize={handleDndFinalize}>
          {#each keyframes as kf, i (kf.id)}
            <div class="kf-card" animate:flip={{ duration: flipDurationMs }}>
              <div class="kf-card-header">
                <span class="kf-position">{i + 1}</span>
                <span class="status-badge" class:pending={kf.status === 'pending'}
                      class:rendering={kf.status === 'rendering'}
                      class:done={kf.status === 'done'}
                      class:error={kf.status === 'error'}>
                  {kf.status}
                </span>
                <select class="model-select" value={kf.model || 'hidream'}
                        onchange={(e) => handleModelChange(kf, e)}>
                  {#each T2I_MODELS as m}
                    <option value={m.id}>{m.label}</option>
                  {/each}
                </select>
              </div>

              <!-- Image area -->
              <div class="kf-image-area">
                {#if kf.status === 'rendering'}
                  <div class="spinner-container"><div class="spinner"></div><span>Rendering...</span></div>
                {:else if kfImageUrl(kf)}
                  <img src={kfImageUrl(kf)} alt="Keyframe {i + 1}" />
                {:else if kf.status === 'error'}
                  <div class="error-container"><span>Error</span><small>{kf.error_message || 'Unknown'}</small></div>
                {:else}
                  <div class="placeholder">No image</div>
                {/if}
              </div>

              <!-- Prompt -->
              <div class="kf-body">
                {#if editing[kf.id]}
                  <textarea bind:value={editPrompts[kf.id]}
                            onkeydown={(e) => editKeydown(e, kf, saveEditKf, cancelEditKf)}
                            rows="4" class="edit-textarea" use:autoFocus></textarea>
                  <div class="edit-actions">
                    <button class="btn-save" onclick={() => saveEditKf(kf)}><Check size={14} /> Save</button>
                    <button class="btn-cancel" onclick={() => cancelEditKf(kf)}><X size={14} /> Cancel</button>
                  </div>
                {:else}
                  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                  <p class="prompt-text clickable" class:empty={!kf.prompt} onclick={() => startEditKf(kf)}>
                    {kf.prompt || 'Click to enter prompt...'}
                  </p>
                {/if}

                {#if editingNeg[kf.id]}
                  <div class="neg-edit">
                    <label class="neg-label">Negative prompt</label>
                    <textarea bind:value={editNegPrompts[kf.id]}
                              onkeydown={(e) => editKeydown(e, kf, saveNegEdit, cancelNegEdit)}
                              rows="2" class="edit-textarea" placeholder="Things to avoid..."
                              use:autoFocus></textarea>
                    <div class="edit-actions">
                      <button class="btn-save" onclick={() => saveNegEdit(kf)}><Check size={14} /> Save</button>
                      <button class="btn-cancel" onclick={() => cancelNegEdit(kf)}><X size={14} /> Cancel</button>
                    </div>
                  </div>
                {:else if kf.negative_prompt}
                  <p class="neg-display"><span class="neg-label-inline">Negative:</span> {kf.negative_prompt}</p>
                {/if}

                {#if rewriting[kf.id]}
                  <div class="rewrite-edit">
                    <label class="rewrite-label">Rewrite instruction</label>
                    <textarea bind:value={rewriteInstructions[kf.id]}
                              onkeydown={(e) => editKeydown(e, kf, submitRewrite, cancelRewrite)}
                              rows="2" class="edit-textarea"
                              placeholder="e.g. Make it nighttime, add rain..."
                              disabled={rewriteLoading[kf.id]}
                              use:autoFocus></textarea>
                    <div class="edit-actions">
                      <button class="btn-save" onclick={() => submitRewrite(kf)}
                              disabled={rewriteLoading[kf.id] || !(rewriteInstructions[kf.id] || '').trim()}>
                        <Wand2 size={14} /> {rewriteLoading[kf.id] ? 'Rewriting...' : 'Rewrite & Render'}
                      </button>
                      <button class="btn-cancel" onclick={() => cancelRewrite(kf)} disabled={rewriteLoading[kf.id]}>
                        <X size={14} /> Cancel
                      </button>
                    </div>
                  </div>
                {/if}
              </div>

              <!-- Actions -->
              <div class="kf-actions">
                {#if kf.prompt && kf.status !== 'rendering'}
                  <button class="btn-icon" onclick={() => handleRerenderKf(kf)} title="Re-render">
                    <RefreshCw size={14} />
                  </button>
                {/if}
                <button class="btn-icon" onclick={() => { const el = document.getElementById(`file-${kf.id}`); el?.click(); }} title="Upload image">
                  <Upload size={14} />
                </button>
                <input id="file-{kf.id}" type="file" accept="image/*"
                       onchange={(e) => handleUpload(kf, e)} class="hidden-input" />
                <button class="btn-icon" onclick={() => startRewrite(kf)} title="Rewrite prompt with AI">
                  <Wand2 size={14} />
                </button>
                <button class="btn-icon" class:btn-active={!!kf.negative_prompt}
                        onclick={() => startEditNeg(kf)} title="Negative prompt">
                  <ThumbsDown size={14} />
                </button>
                <button class="btn-icon btn-danger" onclick={() => handleDeleteKeyframe(kf.id)} title="Delete">
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          {/each}
        </div>
      {:else}
        <div class="empty-panel">
          <p>No keyframes yet. Click Add to create one.</p>
        </div>
      {/if}
    </div>

    <!-- RIGHT: Transitions -->
    <div class="right-panel">
      <div class="panel-header">
        <h3>Transitions</h3>
      </div>

      {#if transitions.length > 0}
        <div class="tr-list">
          {#each transitions as tr, i (tr.id)}
            {@const fromKf = getKeyframe(tr.from_keyframe_id)}
            {@const toKf = getKeyframe(tr.to_keyframe_id)}
            <div class="tr-card">
              <div class="tr-card-header">
                <span class="tr-position">{i + 1}</span>
                <span class="tr-label">Keyframe {tr.position + 1} → {tr.position + 2}</span>
                <span class="status-badge" class:pending={tr.status === 'pending'}
                      class:rendering={tr.status === 'rendering'}
                      class:done={tr.status === 'done'}
                      class:error={tr.status === 'error'}>
                  {tr.status}
                </span>
              </div>

              <div class="tr-thumbs">
                <div class="tr-thumb">
                  {#if kfImageUrl(fromKf)}
                    <img src={kfImageUrl(fromKf)} alt="From" />
                  {:else}
                    <div class="tr-thumb-placeholder">?</div>
                  {/if}
                </div>
                <span class="tr-arrow">→</span>
                <div class="tr-thumb">
                  {#if kfImageUrl(toKf)}
                    <img src={kfImageUrl(toKf)} alt="To" />
                  {:else}
                    <div class="tr-thumb-placeholder">?</div>
                  {/if}
                </div>
              </div>

              <!-- Video preview -->
              <div class="tr-preview">
                {#if tr.status === 'done' && trVideoUrl(tr)}
                  <!-- svelte-ignore a11y_media_has_caption -->
                  <video src={trVideoUrl(tr)} controls loop muted autoplay></video>
                {:else if tr.status === 'rendering'}
                  <div class="render-placeholder"><div class="spinner"></div><span>Rendering...</span></div>
                {:else if tr.status === 'error'}
                  <div class="render-placeholder error"><span>Error</span><small>{tr.error_message || 'Unknown'}</small></div>
                {:else}
                  <div class="render-placeholder">Pending</div>
                {/if}
              </div>

              <!-- Prompt -->
              <div class="tr-body">
                {#if trEditing[tr.id]}
                  <textarea bind:value={trEditPrompts[tr.id]}
                            onkeydown={(e) => editKeydown(e, tr, saveEditTr, cancelEditTr)}
                            rows="3" class="edit-textarea" use:autoFocus></textarea>
                  <div class="edit-actions">
                    <button class="btn-save" onclick={() => saveEditTr(tr)}><Check size={14} /> Save</button>
                    <button class="btn-cancel" onclick={() => cancelEditTr(tr)}><X size={14} /> Cancel</button>
                  </div>
                {:else}
                  <p class="prompt-text">{tr.prompt || '(no description)'}</p>
                {/if}
              </div>

              <div class="tr-actions">
                <button class="btn-icon" onclick={() => handleRerenderTr(tr)} title="Re-render"
                        disabled={tr.status === 'rendering'}>
                  <RefreshCw size={14} />
                </button>
                <button class="btn-icon" onclick={() => startEditTr(tr)} title="Edit prompt">
                  <Pencil size={14} />
                </button>
                {#if tr.status === 'pending'}
                  <button class="btn-render" onclick={() => handleRenderTr(tr)}>Render</button>
                {/if}
              </div>
            </div>
          {/each}
        </div>
      {:else}
        <div class="empty-panel">
          <p>Add keyframes and render them, then click "Sync Transitions" to generate transition clips.</p>
        </div>
      {/if}
    </div>
  </div>
{:else if !creatingSeq}
  <div class="empty-state">
    <p>No sequences yet. Create one to get started.</p>
    <button class="btn-save" onclick={() => { creatingSeq = true; createName = ''; }}>
      <Plus size={14} /> New Sequence
    </button>
  </div>
{/if}

<style>
  /* ── Sequence selector bar ── */
  .seq-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 16px;
  }

  .seq-selector {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .seq-dropdown-wrap {
    position: relative;
  }

  .seq-dropdown-btn {
    background: var(--bg-card);
    color: var(--text);
    border: 1px solid var(--border);
    padding: 8px 14px;
    font-size: 14px;
    font-weight: 500;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 200px;
    justify-content: space-between;
  }

  .seq-dropdown-btn:hover { border-color: var(--text-muted); }

  .seq-menu-overlay {
    position: fixed;
    inset: 0;
    z-index: 99;
  }

  .seq-menu {
    position: absolute;
    top: 100%;
    left: 0;
    margin-top: 4px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    min-width: 200px;
    z-index: 100;
    box-shadow: var(--shadow);
    overflow: hidden;
  }

  .seq-menu-item {
    padding: 8px 14px;
    font-size: 13px;
    cursor: pointer;
    color: var(--text-dim);
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .seq-menu-item:hover { background: var(--bg-card-hover); color: var(--text); }
  .seq-menu-item.active { color: var(--accent); font-weight: 500; }
  .seq-menu-item.create { color: var(--accent); }
  .seq-menu-divider { height: 1px; background: var(--border); }

  .seq-rename-input {
    font-size: 14px;
    padding: 6px 12px;
    min-width: 200px;
  }

  .seq-action-btn {
    background: transparent;
    color: var(--text-dim);
    padding: 6px 8px;
    border-radius: var(--radius);
  }

  .seq-action-btn:hover { color: var(--text); background: var(--bg-card-hover); }
  .seq-action-btn.danger:hover { color: var(--error); }

  .seq-create-btn {
    background: var(--accent);
    color: white;
    font-size: 13px;
    padding: 8px 16px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }

  .seq-create-btn:hover { background: var(--accent-hover); }
  .seq-create-btn.small { padding: 6px 10px; font-size: 12px; }

  .create-seq-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 16px;
    padding: 12px 16px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
  }

  .create-seq-input {
    flex: 1;
    font-size: 14px;
    padding: 6px 12px;
  }

  /* ── Split layout ── */
  .split-layout {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    min-height: 400px;
  }

  .left-panel, .right-panel {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .panel-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
    flex-wrap: wrap;
  }

  .panel-header h3 {
    font-size: 16px;
    font-weight: 600;
    margin-right: auto;
  }

  /* ── Keyframe cards ── */
  .kf-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .kf-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
    transition: border-color 0.15s;
  }

  .kf-card:hover { border-color: var(--text-muted); }

  .kf-card-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
  }

  .kf-position {
    font-weight: 700;
    font-size: 16px;
    color: var(--text);
    min-width: 20px;
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
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 2px 7px;
    border-radius: 10px;
    font-weight: 500;
  }

  .status-badge.pending { background: var(--accent-bg); color: var(--accent); }
  .status-badge.rendering { background: var(--accent-bg); color: var(--accent-hover); }
  .status-badge.done { background: rgba(34, 197, 94, 0.15); color: var(--success); }
  .status-badge.error { background: rgba(239, 68, 68, 0.15); color: var(--error); }

  .kf-image-area {
    aspect-ratio: 16 / 9;
    background: var(--bg);
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }

  .kf-image-area img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .spinner-container, .error-container, .placeholder {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    color: var(--text-muted);
    font-size: 13px;
  }

  .spinner {
    width: 24px;
    height: 24px;
    border: 3px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  .error-container small {
    max-width: 180px;
    text-align: center;
    word-break: break-word;
    color: var(--error);
  }

  .kf-body {
    padding: 10px 12px;
  }

  .prompt-text {
    font-size: 12px;
    color: var(--text-dim);
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .prompt-text.clickable { cursor: pointer; transition: color 0.15s; }
  .prompt-text.clickable:hover { color: var(--text); }
  .prompt-text.empty { font-style: italic; color: var(--text-muted); }

  .edit-textarea {
    width: 100%;
    resize: vertical;
    font-size: 12px;
    min-height: 50px;
  }

  .edit-actions {
    display: flex;
    gap: 6px;
    margin-top: 6px;
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
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid var(--border);
  }

  .neg-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--error); display: block; margin-bottom: 4px; }
  .neg-display { margin-top: 6px; font-size: 11px; color: var(--text-muted); line-height: 1.4; }
  .neg-label-inline { font-size: 11px; color: var(--error); }

  .rewrite-edit {
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid var(--border);
  }

  .rewrite-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--accent); display: block; margin-bottom: 4px; }

  .kf-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    padding: 6px 12px;
    border-top: 1px solid var(--border);
    align-items: center;
  }

  .btn-icon {
    background: transparent;
    color: var(--text-dim);
    padding: 5px 8px;
    font-size: 14px;
    border-radius: var(--radius);
  }

  .btn-icon:hover:not(:disabled) { background: var(--bg-card-hover); color: var(--text); }
  .btn-danger:hover:not(:disabled) { color: var(--error); }
  .btn-active { color: var(--warning); }
  .hidden-input { display: none; }

  /* ── Transition cards ── */
  .tr-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .tr-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }

  .tr-card-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
  }

  .tr-position { font-weight: 700; font-size: 16px; color: var(--text); min-width: 20px; }
  .tr-label { font-size: 12px; color: var(--text-muted); }

  .tr-thumbs {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: var(--bg);
  }

  .tr-thumb {
    width: 80px;
    aspect-ratio: 16 / 9;
    border-radius: var(--radius);
    overflow: hidden;
    background: var(--bg-card);
    flex-shrink: 0;
  }

  .tr-thumb img { width: 100%; height: 100%; object-fit: cover; }
  .tr-thumb-placeholder { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: var(--text-muted); font-size: 12px; }
  .tr-arrow { color: var(--text-muted); font-size: 16px; flex-shrink: 0; }

  .tr-preview {
    padding: 0 12px 8px;
  }

  .tr-preview video {
    width: 100%;
    max-height: 160px;
    border-radius: var(--radius);
    background: #000;
  }

  .render-placeholder {
    min-height: 80px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    color: var(--text-muted);
    font-size: 12px;
  }

  .render-placeholder.error { color: var(--error); }
  .render-placeholder small { font-size: 10px; max-width: 180px; text-align: center; }

  .tr-body { padding: 8px 12px; }

  .tr-actions {
    display: flex;
    gap: 4px;
    padding: 6px 12px;
    border-top: 1px solid var(--border);
    align-items: center;
  }

  .btn-render {
    background: var(--accent);
    color: white;
    font-size: 12px;
    padding: 4px 12px;
    margin-left: auto;
  }

  .btn-render:hover { background: var(--accent-hover); }

  /* ── Toolbar ── */
  .toolbar-btn {
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border);
    font-size: 12px;
    padding: 5px 12px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .toolbar-btn:hover:not(:disabled) { color: var(--text-dim); border-color: var(--text-muted); }

  /* ── Empty states ── */
  .empty-panel {
    text-align: center;
    padding: 60px 16px;
    color: var(--text-muted);
    border: 2px dashed var(--border);
    border-radius: var(--radius-lg);
  }

  .empty-panel p { font-size: 14px; }

  .empty-state {
    text-align: center;
    padding: 80px 20px;
    color: var(--text-muted);
    border: 2px dashed var(--border);
    border-radius: var(--radius-lg);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 16px;
  }

  .empty-state p { font-size: 16px; }
</style>
