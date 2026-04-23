<script>
  import { dndzone } from 'svelte-dnd-action';
  import { flip } from 'svelte/animate';
  import { RefreshCw, Pencil, Trash2, Check, X, ThumbsDown, Wand2, Upload, Plus,
           ChevronDown, RotateCcw, GitMerge, Lock, Unlock, Blend } from 'lucide-svelte';
  import {
    listSequences, createSequence, updateSequence, deleteSequence, activateSequence,
    seqAddKeyframe, seqUpdateKeyframe, seqDeleteKeyframe, seqReorderKeyframes,
    seqKeyframeStatus, seqRenderKeyframe, seqRerenderKeyframe, seqRewriteKeyframe,
    seqUploadKeyframe, seqAddKeyframeImage, seqMergeSequence, seqCombineKeyframe,
    seqSyncTransitions, seqTransitionStatus, seqUpdateTransition,
    seqRenderTransition, seqRerenderTransition, seqLockTransition, seqUnlockTransition,
    T2I_MODELS, galleryList, RESOLUTIONS, setResolution,
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

  // ── Sequence-level negative prompt ──
  let editingSeqNeg = $state(false);
  let seqNegValue = $state('');

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
  let trEditingNeg = $state({});
  let trEditNegPrompts = $state({});
  let trPolling = $state({});

  // ── Add keyframe state ──
  let showGalleryPicker = $state(false);
  let galleryImages = $state([]);
  let galleryPickerKfId = $state(null);  // null = add new, string = load into existing
  let showMergePicker = $state(false);
  let otherSequences = $derived(sequences.filter(s => s.id !== activeSeqId));

  const flipDurationMs = 200;

  // Build transition lookup: for each adjacent keyframe pair, find the transition
  function getTransitionBetween(i) {
    if (i >= keyframes.length - 1) return null;
    return transitions.find(t =>
      t.from_keyframe_id === keyframes[i].id && t.to_keyframe_id === keyframes[i + 1].id
    ) || null;
  }

  // ── Drag and drop ──
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
      // Reload to restore correct order
      init();
    }
  }

  // ── Lock/unlock transitions ──
  async function handleToggleLock(tr) {
    try {
      const data = tr.locked
        ? await seqUnlockTransition(activeSeqId, tr.id)
        : await seqLockTransition(activeSeqId, tr.id);
      replaceSeq(data.sequence);
      onstatus?.({ detail: tr.locked ? 'Unlocked.' : 'Locked.' });
    } catch (e) {
      onstatus?.({ detail: `Lock failed: ${e.message}` });
    }
  }

  // ── Init ──
  async function init() {
    if (!projectId) return;
    try {
      const data = await listSequences();
      sequences = data.sequences || [];
      activeSeqId = data.active_sequence_id;
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
    try { await activateSequence(id); } catch {}
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
      await deleteSequence(activeSeqId);
      sequences = sequences.filter(s => s.id !== activeSeqId);
      activeSeqId = sequences[0]?.id || null;
      onstatus?.({ detail: 'Sequence deleted.' });
    } catch (e) {
      onstatus?.({ detail: `Delete failed: ${e.message}` });
    }
  }

  function startEditSeqNeg() {
    seqNegValue = activeSeq?.negative_prompt || '';
    editingSeqNeg = true;
  }

  async function saveSeqNeg() {
    if (!activeSeq) return;
    try {
      await updateSequence(activeSeqId, { negative_prompt: seqNegValue });
      activeSeq.negative_prompt = seqNegValue;
      editingSeqNeg = false;
      onstatus?.({ detail: 'Sequence negative prompt updated.' });
    } catch (e) { onstatus?.({ detail: `Update failed: ${e.message}` }); }
  }

  function cancelSeqNeg() { editingSeqNeg = false; }

  let projectWidth = $derived(project?.width || 1024);
  let projectHeight = $derived(project?.height || 576);

  async function handleResolutionChange(e) {
    const r = RESOLUTIONS[e.target.selectedIndex];
    try {
      await setResolution(r.w, r.h);
      project.width = r.w;
      project.height = r.h;
      onstatus?.({ detail: `Resolution set to ${r.w}x${r.h}. New renders will use this size.` });
    } catch (err) { onstatus?.({ detail: `Failed: ${err.message}` }); }
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

  async function openGalleryPicker(kfId = null) {
    galleryPickerKfId = kfId;
    try {
      const data = await galleryList();
      galleryImages = (data.images || []).filter(i => i.image_url);
      if (galleryImages.length === 0) {
        onstatus?.({ detail: 'No images in gallery yet.' });
        return;
      }
      showGalleryPicker = true;
    } catch (e) {
      onstatus?.({ detail: `Failed to load gallery: ${e.message}` });
    }
  }

  async function handlePickGalleryImage(img) {
    showGalleryPicker = false;
    if (!activeSeqId) return;
    if (galleryPickerKfId) {
      // Load into existing keyframe
      const kf = keyframes.find(k => k.id === galleryPickerKfId);
      if (!kf) return;
      try {
        // Upload the gallery image to this keyframe
        const resp = await fetch(img.image_url);
        const blob = await resp.blob();
        const result = await seqUploadKeyframe(activeSeqId, kf.id, blob);
        kf.image_filename = result.image_filename;
        kf.seed = result.seed;
        kf.status = result.status;
        if (img.prompt && !kf.prompt) kf.prompt = img.prompt;
        onstatus?.({ detail: 'Loaded image from gallery.' });
      } catch (e) {
        onstatus?.({ detail: `Failed: ${e.message}` });
      }
    } else {
      // Add as new keyframe
      try {
        const data = await seqAddKeyframe(activeSeqId, img.id);
        replaceSeq(data.sequence);
        onstatus?.({ detail: 'Added keyframe from gallery.' });
      } catch (e) {
        onstatus?.({ detail: `Add failed: ${e.message}` });
      }
    }
  }

  // Global paste listener: Ctrl+V adds a new keyframe from clipboard
  async function handleGlobalPaste(e) {
    if (!activeSeqId) return;
    // Don't intercept paste into text fields
    const tag = e.target?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        e.preventDefault();
        const blob = item.getAsFile();
        if (!blob) return;
        try {
          const data = await seqAddKeyframeImage(activeSeqId, blob);
          replaceSeq(data.sequence);
          onstatus?.({ detail: 'Added keyframe from clipboard.' });
        } catch (err) {
          onstatus?.({ detail: `Paste failed: ${err.message}` });
        }
        return;
      }
    }
  }

  $effect(() => {
    if (activeSeqId) {
      document.addEventListener('paste', handleGlobalPaste);
      return () => document.removeEventListener('paste', handleGlobalPaste);
    }
  });

  function openMergePicker() {
    if (otherSequences.length === 0) {
      onstatus?.({ detail: 'No other sequences to merge.' });
      return;
    }
    showMergePicker = true;
  }

  async function handleMergeSequence(sourceId) {
    showMergePicker = false;
    if (!activeSeqId) return;
    try {
      const data = await seqMergeSequence(activeSeqId, sourceId);
      replaceSeq(data.sequence);
      onstatus?.({ detail: 'Sequence merged.' });
    } catch (e) {
      onstatus?.({ detail: `Merge failed: ${e.message}` });
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

  // ── Keyframe editing ──
  function startEditKf(kf) { editPrompts[kf.id] = kf.prompt; editing[kf.id] = true; }
  async function saveEditKf(kf) {
    try {
      await seqUpdateKeyframe(activeSeqId, kf.id, { prompt: editPrompts[kf.id] });
      kf.prompt = editPrompts[kf.id];
      editing[kf.id] = false;
      if (kf.prompt.trim()) {
        onstatus?.({ detail: 'Prompt updated. Rendering...' });
        handleRerenderKf(kf);
      } else {
        onstatus?.({ detail: 'Prompt updated.' });
      }
    } catch (e) { onstatus?.({ detail: `Update failed: ${e.message}` }); }
  }
  function cancelEditKf(kf) { editing[kf.id] = false; }

  function startEditNeg(kf) { editNegPrompts[kf.id] = kf.negative_prompt || ''; editingNeg[kf.id] = true; }
  async function saveNegEdit(kf) {
    try {
      await seqUpdateKeyframe(activeSeqId, kf.id, { negative_prompt: editNegPrompts[kf.id] });
      kf.negative_prompt = editNegPrompts[kf.id];
      editingNeg[kf.id] = false;
      onstatus?.({ detail: 'Negative prompt updated.' });
    } catch (e) { onstatus?.({ detail: `Update failed: ${e.message}` }); }
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
    } catch (e) { onstatus?.({ detail: `Rewrite failed: ${e.message}` }); }
    finally { rewriteLoading[kf.id] = false; }
  }
  function cancelRewrite(kf) { rewriting[kf.id] = false; }

  // ── Keyframe render ──
  async function handleRenderKf(kf) {
    onstatus?.({ detail: `Rendering keyframe...` });
    kf.status = 'rendering';
    try { await seqRenderKeyframe(activeSeqId, kf.id); pollKeyframe(kf); }
    catch (e) { onstatus?.({ detail: `Render failed: ${e.message}` }); }
  }

  async function handleRerenderKf(kf) {
    onstatus?.({ detail: `Re-rendering keyframe...` });
    kf.status = 'rendering';
    try { await seqRerenderKeyframe(activeSeqId, kf.id); pollKeyframe(kf); }
    catch (e) { onstatus?.({ detail: `Re-render failed: ${e.message}` }); }
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
    } catch (e) { onstatus?.({ detail: `Failed: ${e.message}` }); }
  }

  async function handleUpload(kf, e) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const result = await seqUploadKeyframe(activeSeqId, kf.id, file);
      kf.image_filename = result.image_filename;
      kf.seed = result.seed;
      kf.status = result.status;
      onstatus?.({ detail: 'Image uploaded.' });
    } catch (err) { onstatus?.({ detail: `Upload failed: ${err.message}` }); }
    e.target.value = '';
  }

  // ── Combine keyframes ──
  async function handleCombine(kf, i) {
    if (!activeSeqId || i === 0) return;
    const prevKf = keyframes[i - 1];
    if (!prevKf?.image_filename || !kf?.image_filename) {
      onstatus?.({ detail: 'Both keyframes must have rendered images to combine.' });
      return;
    }
    try {
      const data = await seqCombineKeyframe(activeSeqId, kf.id);
      replaceSeq(data.sequence);
      onstatus?.({ detail: 'Combine keyframe inserted. Enter a prompt and render.' });
    } catch (e) {
      onstatus?.({ detail: `Combine failed: ${e.message}` });
    }
  }

  async function handleDeriveFromPrev(kf, i) {
    if (!activeSeqId || i === 0) return;
    const prevKf = keyframes[i - 1];
    if (!prevKf?.image_filename) {
      onstatus?.({ detail: 'Previous keyframe must have a rendered image.' });
      return;
    }
    try {
      await seqUpdateKeyframe(activeSeqId, kf.id, {
        model: 'flux2_klein',
        figure1_kf_id: prevKf.id,
        figure2_kf_id: prevKf.id,
      });
      kf.model = 'flux2_klein';
      kf.figure1_kf_id = prevKf.id;
      kf.figure2_kf_id = prevKf.id;
      onstatus?.({ detail: 'Set to Klein model with previous keyframe as input. Enter a prompt and render.' });
    } catch (e) {
      onstatus?.({ detail: `Failed: ${e.message}` });
    }
  }

  // ── Transition operations ──
  async function handleSyncTransitions() {
    if (!activeSeqId) return;
    onstatus?.({ detail: 'Syncing transitions...' });
    try {
      const data = await seqSyncTransitions(activeSeqId);
      replaceSeq(data.sequence);
      onstatus?.({ detail: 'Transitions synced.' });
    } catch (e) { onstatus?.({ detail: `Sync failed: ${e.message}` }); }
  }

  function startEditTr(tr) { trEditPrompts[tr.id] = tr.prompt; trEditing[tr.id] = true; }
  async function saveEditTr(tr) {
    try {
      await seqUpdateTransition(activeSeqId, tr.id, { prompt: trEditPrompts[tr.id] });
      tr.prompt = trEditPrompts[tr.id];
      trEditing[tr.id] = false;
      onstatus?.({ detail: 'Transition prompt updated. Re-rendering...' });
      handleRerenderTr(tr);
    } catch (e) { onstatus?.({ detail: `Update failed: ${e.message}` }); }
  }
  function cancelEditTr(tr) { trEditing[tr.id] = false; }

  function startEditTrNeg(tr) { trEditNegPrompts[tr.id] = tr.negative_prompt || ''; trEditingNeg[tr.id] = true; }
  async function saveTrNegEdit(tr) {
    try {
      await seqUpdateTransition(activeSeqId, tr.id, { negative_prompt: trEditNegPrompts[tr.id] });
      tr.negative_prompt = trEditNegPrompts[tr.id];
      trEditingNeg[tr.id] = false;
      onstatus?.({ detail: 'Negative prompt updated. Re-rendering...' });
      handleRerenderTr(tr);
    } catch (e) { onstatus?.({ detail: `Update failed: ${e.message}` }); }
  }
  function cancelTrNegEdit(tr) { trEditingNeg[tr.id] = false; }

  async function handleTrDurationChange(tr, e) {
    const val = parseInt(e.target.value, 10);
    if (isNaN(val) || val < 1) return;
    tr.duration = val;
    try {
      await seqUpdateTransition(activeSeqId, tr.id, { duration: val });
      onstatus?.({ detail: `Duration set to ${val}s. Re-render to apply.` });
    } catch (err) { onstatus?.({ detail: `Failed: ${err.message}` }); }
  }

  async function handleRenderTr(tr) {
    onstatus?.({ detail: `Rendering transition...` });
    tr.status = 'rendering';
    try { await seqRenderTransition(activeSeqId, tr.id); pollTransition(tr); }
    catch (e) { onstatus?.({ detail: `Render failed: ${e.message}` }); }
  }

  async function handleRerenderTr(tr) {
    onstatus?.({ detail: `Re-rendering transition...` });
    tr.status = 'rendering';
    try { await seqRerenderTransition(activeSeqId, tr.id); pollTransition(tr); }
    catch (e) { onstatus?.({ detail: `Re-render failed: ${e.message}` }); }
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
    return `/api/projects/${projectId}/images/${kf.image_filename}?v=${kf.seed || Date.now()}`;
  }

  function trVideoUrl(tr) {
    if (!tr?.video_filename || !projectId) return null;
    return `/api/projects/${projectId}/videos/${tr.video_filename}?v=${tr.seed || Date.now()}`;
  }

  function getKeyframe(id) { return keyframes.find(kf => kf.id === id); }

  function horizontalScroll(node) {
    function onWheel(e) {
      if (e.deltaY !== 0) {
        e.preventDefault();
        node.scrollLeft += e.deltaY;
      }
    }
    node.addEventListener('wheel', onWheel, { passive: false });
    return { destroy() { node.removeEventListener('wheel', onWheel); } };
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
              title="Rename"><Pencil size={14} /></button>
      <button class="seq-action-btn danger" onclick={handleDeleteSequence} title="Delete sequence">
        <Trash2 size={14} /></button>
      <button class="seq-create-btn small" onclick={() => { creatingSeq = true; createName = ''; }}>
        <Plus size={14} /></button>
    {/if}
  </div>
  {#if activeSeq}
    <div class="seq-toolbar">
      <button class="toolbar-btn" onclick={handleAddKeyframe}>
        <Plus size={14} /> Add Keyframe
      </button>
      {#if otherSequences.length > 0}
        <button class="toolbar-btn" onclick={openMergePicker} title="Append another sequence">
          <GitMerge size={14} /> Merge
        </button>
      {/if}
      {#if keyframes.some(kf => kf.status === 'done')}
        <button class="toolbar-btn" onclick={handleSyncTransitions}>
          <RotateCcw size={14} /> Sync Transitions
        </button>
      {/if}
    </div>
  {/if}
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

<!-- Sequence negative prompt -->
{#if activeSeq}
  <div class="seq-settings-bar">
    <div class="seq-neg-section">
      {#if editingSeqNeg}
        <label class="seq-neg-label">Sequence negative prompt</label>
        <div class="seq-neg-edit">
          <textarea bind:value={seqNegValue}
                    onkeydown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveSeqNeg(); } else if (e.key === 'Escape') cancelSeqNeg(); }}
                    rows="2" class="edit-textarea" placeholder="Applies to all keyframes and transitions in this sequence..."
                    use:autoFocus></textarea>
          <div class="edit-actions">
            <button class="btn-save" onclick={saveSeqNeg}><Check size={14} /> Save</button>
            <button class="btn-cancel" onclick={cancelSeqNeg}><X size={14} /> Cancel</button>
          </div>
        </div>
      {:else}
        <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
        <div class="seq-neg-display" onclick={startEditSeqNeg}>
          <span class="seq-neg-label">Negative:</span>
          <span class="seq-neg-text">{activeSeq.negative_prompt || 'none (click to set)'}</span>
        </div>
      {/if}
    </div>
    <div class="seq-res-section">
      <span class="seq-res-label">Resolution:</span>
      <select class="seq-res-select" onchange={handleResolutionChange}>
        {#each RESOLUTIONS as r}
          <option selected={r.w === projectWidth && r.h === projectHeight}>{r.label}</option>
        {/each}
      </select>
    </div>
  </div>
{/if}

<!-- Horizontal timeline -->
{#if activeSeq}
  {#if keyframes.length > 0}
    <div class="timeline-scroll" use:horizontalScroll>
      <!-- Row 1: Keyframes (draggable) + add button -->
      <div class="kf-row-wrap">
      <div class="kf-row"
           use:dndzone={{ items: keyframes, flipDurationMs, type: 'seq-keyframes' }}
           onconsider={handleDndConsider}
           onfinalize={handleDndFinalize}>
        {#each keyframes as kf, i (kf.id)}
          <div class="tl-card tl-keyframe" class:locked={kf.locked}
               animate:flip={{ duration: flipDurationMs }}>
            <div class="tl-header">
              <span class="tl-position">{i + 1}</span>
              {#if kf.locked}
                <Lock size={12} class="lock-indicator" />
              {/if}
              {#if kf.figure1_kf_id}
                <Blend size={12} class="combine-indicator" />
              {/if}
              <span class="status-badge" class:pending={kf.status === 'pending'}
                    class:rendering={kf.status === 'rendering'}
                    class:done={kf.status === 'done'}
                    class:error={kf.status === 'error'}>
                {kf.status}
              </span>
              {#if !kf.locked}
                <select class="model-select" value={kf.model || 'hidream'}
                        onchange={(e) => handleModelChange(kf, e)}>
                  {#each T2I_MODELS as m}
                    <option value={m.id}>{m.label}</option>
                  {/each}
                </select>
              {/if}
            </div>

            <div class="tl-image" style="aspect-ratio: {projectWidth} / {projectHeight};">
              {#if kf.status === 'rendering'}
                <div class="spinner-container"><div class="spinner"></div><span>Rendering...</span></div>
              {:else if kfImageUrl(kf)}
                <img src={kfImageUrl(kf)} alt="Keyframe {i + 1}" />
              {:else if kf.status === 'error'}
                <div class="error-container"><span>Error</span><small>{kf.error_message || 'Unknown'}</small></div>
              {:else if !kf.locked}
                <div class="blank-kf-options">
                  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                  <div class="gallery-placeholder" onclick={() => openGalleryPicker(kf.id)} title="Load from gallery">
                    <Plus size={24} />
                  </div>
                  {#if i > 0 && keyframes[i - 1]?.image_filename}
                    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                    <div class="derive-placeholder" onclick={() => handleDeriveFromPrev(kf, i)} title="Derive from previous keyframe (Klein)">
                      <Blend size={24} />
                    </div>
                  {/if}
                </div>
              {:else}
                <div class="placeholder-box">Locked</div>
              {/if}
            </div>

            <div class="tl-body">
              {#if !kf.locked && editing[kf.id]}
                <textarea bind:value={editPrompts[kf.id]}
                          onkeydown={(e) => editKeydown(e, kf, saveEditKf, cancelEditKf)}
                          rows="3" class="edit-textarea" use:autoFocus></textarea>
                <div class="edit-actions">
                  <button class="btn-save" onclick={() => saveEditKf(kf)}><Check size={14} /> Save</button>
                  <button class="btn-cancel" onclick={() => cancelEditKf(kf)}><X size={14} /> Cancel</button>
                </div>
              {:else}
                <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                <p class="prompt-text" class:clickable={!kf.locked} class:empty={!kf.prompt}
                   onclick={() => !kf.locked && startEditKf(kf)}>
                  {kf.prompt || (kf.locked ? '(locked)' : 'Click to enter prompt...')}
                </p>
              {/if}

              {#if !kf.locked && editingNeg[kf.id]}
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
                <p class="neg-display"><span class="neg-label-inline">Neg:</span> {kf.negative_prompt}</p>
              {/if}

              {#if !kf.locked && rewriting[kf.id]}
                <div class="rewrite-edit">
                  <label class="rewrite-label">Rewrite instruction</label>
                  <textarea bind:value={rewriteInstructions[kf.id]}
                            onkeydown={(e) => editKeydown(e, kf, submitRewrite, cancelRewrite)}
                            rows="2" class="edit-textarea"
                            placeholder="e.g. Make it nighttime..."
                            disabled={rewriteLoading[kf.id]}
                            use:autoFocus></textarea>
                  <div class="edit-actions">
                    <button class="btn-save" onclick={() => submitRewrite(kf)}
                            disabled={rewriteLoading[kf.id] || !(rewriteInstructions[kf.id] || '').trim()}>
                      <Wand2 size={14} /> {rewriteLoading[kf.id] ? 'Rewriting...' : 'Rewrite'}
                    </button>
                    <button class="btn-cancel" onclick={() => cancelRewrite(kf)} disabled={rewriteLoading[kf.id]}>
                      <X size={14} />
                    </button>
                  </div>
                </div>
              {/if}
            </div>

            {#if !kf.locked}
              <div class="tl-actions">
                {#if kf.prompt && kf.status !== 'rendering'}
                  <button class="btn-icon" onclick={() => handleRerenderKf(kf)} title="Re-render">
                    <RefreshCw size={14} />
                  </button>
                {/if}
                <button class="btn-icon" onclick={() => { document.getElementById(`file-${kf.id}`)?.click(); }} title="Upload">
                  <Upload size={14} />
                </button>
                <input id="file-{kf.id}" type="file" accept="image/*"
                       onchange={(e) => handleUpload(kf, e)} class="hidden-input" />
                <button class="btn-icon" onclick={() => startRewrite(kf)} title="Rewrite with AI">
                  <Wand2 size={14} />
                </button>
                <button class="btn-icon" class:btn-active={!!kf.negative_prompt}
                        onclick={() => startEditNeg(kf)} title="Negative prompt">
                  <ThumbsDown size={14} />
                </button>
                {#if i > 0 && keyframes[i - 1]?.image_filename && kf.image_filename}
                  <button class="btn-icon btn-combine" onclick={() => handleCombine(kf, i)} title="Combine with previous keyframe (Klein)">
                    <Blend size={14} />
                  </button>
                {/if}
                <button class="btn-icon btn-danger" onclick={() => handleDeleteKeyframe(kf.id)} title="Delete">
                  <Trash2 size={14} />
                </button>
              </div>
            {/if}
          </div>
        {/each}
      </div>

      <!-- Add button (outside dndzone) -->
      <button class="tl-add-btn" onclick={handleAddKeyframe} title="Add keyframe">
        <Plus size={20} />
      </button>
      </div>

      <!-- Row 2: TV transitions (staggered) -->
      {#if keyframes.length > 1}
        <div class="tr-row" style="padding-left: {(640 + 24) / 2}px;">
          {#each keyframes as _, i}
            {#if i < keyframes.length - 1}
              {@const tr = getTransitionBetween(i)}
              {#if tr}
                <div class="tv-set">
                  <div class="tv-antennas">
                    <div class="tv-antenna left"></div>
                    <div class="tv-antenna right"></div>
                  </div>
                  <div class="tv-body">
                    <div class="tv-screen-area">
                      <div class="tv-screen" style="aspect-ratio: {projectWidth} / {projectHeight};">
                        <div class="tv-screen-inner">
                          {#if tr.status === 'done' && trVideoUrl(tr)}
                            <!-- svelte-ignore a11y_media_has_caption -->
                            <video src={trVideoUrl(tr)} controls loop muted autoplay></video>
                          {:else if tr.status === 'rendering'}
                            <div class="tv-static"><div class="spinner"></div><span>Rendering...</span></div>
                          {:else if tr.status === 'error'}
                            <div class="tv-static error"><span>ERROR</span><small>{tr.error_message || 'No signal'}</small></div>
                          {:else}
                            <div class="tv-static"><span class="tv-no-signal">NO SIGNAL</span></div>
                          {/if}
                        </div>
                      </div>
                    </div>
                    <div class="tv-controls">
                      <div class="tv-label">{i + 1}→{i + 2}</div>
                      <span class="status-badge" class:pending={tr.status === 'pending'}
                            class:rendering={tr.status === 'rendering'}
                            class:done={tr.status === 'done'}
                            class:error={tr.status === 'error'}>
                        {tr.status}
                      </span>
                      {#if !tr.locked}
                        <div class="tv-duration">
                          <input type="number" min="1" max="120"
                                 value={tr.duration || 10}
                                 onchange={(e) => handleTrDurationChange(tr, e)}
                                 class="tv-duration-input" />
                          <span class="tv-duration-label">sec</span>
                        </div>
                      {:else}
                        <div class="tv-duration">
                          <span class="tv-duration-label">{tr.duration || 10}s</span>
                        </div>
                      {/if}
                      <button class="tv-lock-btn" onclick={() => handleToggleLock(tr)}
                              title={tr.locked ? 'Unlock transition' : 'Lock transition'}>
                        {#if tr.locked}
                          <Lock size={14} />
                        {:else}
                          <Unlock size={14} />
                        {/if}
                      </button>
                    </div>
                  </div>
                  <div class="tv-footer" class:locked={tr.locked}>
                    <div class="tl-body">
                      {#if !tr.locked && trEditing[tr.id]}
                        <textarea bind:value={trEditPrompts[tr.id]}
                                  onkeydown={(e) => editKeydown(e, tr, saveEditTr, cancelEditTr)}
                                  rows="2" class="edit-textarea" use:autoFocus></textarea>
                        <div class="edit-actions">
                          <button class="btn-save" onclick={() => saveEditTr(tr)}><Check size={14} /> Save</button>
                          <button class="btn-cancel" onclick={() => cancelEditTr(tr)}><X size={14} /> Cancel</button>
                        </div>
                      {:else}
                        <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                        <p class="prompt-text" class:clickable={!tr.locked}
                           onclick={() => !tr.locked && startEditTr(tr)}>
                          {tr.prompt || (tr.locked ? '(locked)' : '(click to edit description)')}
                        </p>
                      {/if}

                      {#if !tr.locked && trEditingNeg[tr.id]}
                        <div class="neg-edit">
                          <label class="neg-label">Negative prompt</label>
                          <textarea bind:value={trEditNegPrompts[tr.id]}
                                    onkeydown={(e) => editKeydown(e, tr, saveTrNegEdit, cancelTrNegEdit)}
                                    rows="2" class="edit-textarea" placeholder="Things to avoid..."
                                    use:autoFocus></textarea>
                          <div class="edit-actions">
                            <button class="btn-save" onclick={() => saveTrNegEdit(tr)}><Check size={14} /> Save</button>
                            <button class="btn-cancel" onclick={() => cancelTrNegEdit(tr)}><X size={14} /> Cancel</button>
                          </div>
                        </div>
                      {:else if tr.negative_prompt}
                        <p class="neg-display"><span class="neg-label-inline">Neg:</span> {tr.negative_prompt}</p>
                      {/if}
                    </div>
                    {#if !tr.locked}
                      <div class="tl-actions">
                        <button class="btn-icon" onclick={() => handleRerenderTr(tr)} title="Re-render"
                                disabled={tr.status === 'rendering'}>
                          <RefreshCw size={14} />
                        </button>
                        <button class="btn-icon" class:btn-active={!!tr.negative_prompt}
                                onclick={() => startEditTrNeg(tr)} title="Negative prompt">
                          <ThumbsDown size={14} />
                        </button>
                        {#if tr.status === 'pending'}
                          <button class="btn-render" onclick={() => handleRenderTr(tr)}>Render</button>
                        {/if}
                      </div>
                    {/if}
                  </div>
                </div>
              {:else}
                <div class="tv-placeholder"></div>
              {/if}
            {/if}
          {/each}
        </div>
      {/if}
    </div>
  {:else}
    <div class="empty-panel">
      <p>No keyframes yet. Click "Add Keyframe" to start building your sequence.</p>
    </div>
  {/if}
{:else if !creatingSeq}
  <div class="empty-state">
    <p>No sequences yet. Create one to get started.</p>
    <button class="btn-save" onclick={() => { creatingSeq = true; createName = ''; }}>
      <Plus size={14} /> New Sequence
    </button>
  </div>
{/if}

<!-- Gallery picker modal -->
{#if showGalleryPicker}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="picker-overlay" onclick={() => showGalleryPicker = false}>
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div class="picker-modal" onclick={(e) => e.stopPropagation()}>
      <h3>{galleryPickerKfId ? 'Load image from gallery' : 'Add keyframe from gallery'}</h3>
      <div class="picker-grid">
        {#each galleryImages as img (img.id)}
          <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
          <div class="picker-item" onclick={() => handlePickGalleryImage(img)}>
            <img src={img.image_url} alt={img.prompt} />
            {#if img.prompt}
              <p class="picker-prompt">{img.prompt}</p>
            {/if}
          </div>
        {/each}
      </div>
      <button class="picker-cancel" onclick={() => showGalleryPicker = false}>Cancel</button>
    </div>
  </div>
{/if}

<!-- Merge sequence picker modal -->
{#if showMergePicker}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="picker-overlay" onclick={() => showMergePicker = false}>
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div class="picker-modal narrow" onclick={(e) => e.stopPropagation()}>
      <h3>Merge sequence into "{activeSeq?.name}"</h3>
      <p class="merge-hint">All keyframes from the selected sequence will be appended to the end of this one.</p>
      <div class="merge-list">
        {#each otherSequences as seq (seq.id)}
          <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
          <div class="merge-item" onclick={() => handleMergeSequence(seq.id)}>
            <span class="merge-name">{seq.name}</span>
            <span class="merge-count">{seq.keyframes.length} keyframe{seq.keyframes.length !== 1 ? 's' : ''}</span>
          </div>
        {/each}
      </div>
      <button class="picker-cancel" onclick={() => showMergePicker = false}>Cancel</button>
    </div>
  </div>
{/if}

<style>
  /* ── Sequence selector bar ── */
  .seq-bar {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }

  .seq-selector {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .seq-toolbar {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-left: auto;
  }

  .seq-dropdown-wrap { position: relative; }

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

  .seq-menu-overlay { position: fixed; inset: 0; z-index: 99; }
  .seq-menu {
    position: absolute; top: 100%; left: 0; margin-top: 4px;
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: var(--radius); min-width: 200px; z-index: 100;
    box-shadow: var(--shadow); overflow: hidden;
  }
  .seq-menu-item {
    padding: 8px 14px; font-size: 13px; cursor: pointer;
    color: var(--text-dim); display: flex; align-items: center; gap: 6px;
  }
  .seq-menu-item:hover { background: var(--bg-card-hover); color: var(--text); }
  .seq-menu-item.active { color: var(--accent); font-weight: 500; }
  .seq-menu-item.create { color: var(--accent); }
  .seq-menu-divider { height: 1px; background: var(--border); }

  .seq-rename-input { font-size: 14px; padding: 6px 12px; min-width: 200px; }

  .seq-action-btn {
    background: transparent; color: var(--text-dim);
    padding: 6px 8px; border-radius: var(--radius);
  }
  .seq-action-btn:hover { color: var(--text); background: var(--bg-card-hover); }
  .seq-action-btn.danger:hover { color: var(--error); }

  .seq-create-btn {
    background: var(--accent); color: white; font-size: 13px;
    padding: 8px 16px; display: inline-flex; align-items: center; gap: 6px;
  }
  .seq-create-btn:hover { background: var(--accent-hover); }
  .seq-create-btn.small { padding: 6px 10px; font-size: 12px; }

  .create-seq-bar {
    display: flex; align-items: center; gap: 8px; margin-bottom: 16px;
    padding: 12px 16px; background: var(--bg-card);
    border: 1px solid var(--border); border-radius: var(--radius-lg);
  }
  .create-seq-input { flex: 1; font-size: 14px; padding: 6px 12px; }

  /* ── Sequence settings bar ── */
  .seq-settings-bar {
    display: flex;
    align-items: flex-start;
    gap: 16px;
    margin-bottom: 12px;
    padding: 8px 14px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }

  .seq-neg-section { flex: 1; min-width: 0; }

  .seq-neg-display {
    display: flex;
    align-items: baseline;
    gap: 6px;
    cursor: pointer;
    transition: color 0.15s;
  }
  .seq-neg-display:hover { color: var(--text); }

  .seq-neg-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--error);
    flex-shrink: 0;
  }

  .seq-neg-text {
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.4;
  }

  .seq-neg-edit { margin-top: 4px; }

  .seq-res-section {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }

  .seq-res-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-muted);
    white-space: nowrap;
  }

  .seq-res-select {
    font-family: inherit;
    font-size: 12px;
    color: var(--text-dim);
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 4px 8px;
  }

  /* ── Horizontal timeline ── */
  .timeline-scroll {
    overflow-x: auto;
    overflow-y: hidden;
    padding-bottom: 8px;
    /* Fill remaining viewport: header ~70px, tabs ~44px, seq-bar ~40px, settings ~46px, status ~40px, padding ~76px */
    height: calc(100dvh - 316px);
    min-height: 200px;
  }

  .timeline-scroll::-webkit-scrollbar { height: 14px; }
  .timeline-scroll::-webkit-scrollbar-track { background: var(--bg); border-radius: 7px; }
  .timeline-scroll::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 7px;
    border: 3px solid var(--bg);
  }
  .timeline-scroll::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }
  .timeline-scroll { scrollbar-width: auto; scrollbar-color: var(--border) var(--bg); }

  .kf-row-wrap {
    display: flex;
    gap: 24px;
    align-items: stretch;
  }

  .kf-row {
    display: flex;
    gap: 24px;
    min-width: min-content;
  }

  .tr-row {
    display: flex;
    gap: 24px;
    min-width: min-content;
    margin-top: 16px;
  }

  .tl-card {
    display: flex;
    flex-direction: column;
    width: 640px;
    flex-shrink: 0;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
    transition: border-color 0.15s;
  }
  .tl-card:hover { border-color: var(--text-muted); }


  .tl-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 10px;
    border-bottom: 1px solid var(--border);
  }

  .tl-position {
    font-weight: 700; font-size: 15px; color: var(--text); min-width: 18px;
  }

  .tl-arrow-label {
    font-weight: 600; font-size: 13px; color: var(--text-muted);
  }

  .model-select {
    margin-left: auto; font-family: inherit; font-size: 10px;
    color: var(--text-dim); background: var(--bg-input);
    border: 1px solid var(--border); border-radius: var(--radius);
    padding: 1px 4px;
  }

  .status-badge {
    font-size: 9px; text-transform: uppercase; letter-spacing: 0.05em;
    padding: 1px 6px; border-radius: 10px; font-weight: 500;
  }
  .status-badge.pending { background: var(--accent-bg); color: var(--accent); }
  .status-badge.rendering { background: var(--accent-bg); color: var(--accent-hover); }
  .status-badge.done { background: rgba(34, 197, 94, 0.15); color: var(--success); }
  .status-badge.error { background: rgba(239, 68, 68, 0.15); color: var(--error); }

  /* ── Image / Video areas ── */
  .tl-image {
    background: var(--bg);
    display: flex; align-items: center; justify-content: center;
    overflow: hidden;
    /* aspect-ratio set via inline style from project resolution */
  }
  .tl-image img { width: 100%; height: 100%; object-fit: contain; }

  /* ── TV Set ── */
  .tv-set {
    width: 640px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
  }

  .tv-placeholder {
    width: 640px;
    flex-shrink: 0;
  }

  .tv-antennas {
    display: flex;
    justify-content: center;
    gap: 30px;
    height: 28px;
    position: relative;
  }

  .tv-antenna {
    width: 3px;
    height: 28px;
    background: linear-gradient(to top, #555, #888);
    border-radius: 2px 2px 0 0;
  }
  .tv-antenna.left { transform: rotate(-20deg); transform-origin: bottom center; }
  .tv-antenna.right { transform: rotate(20deg); transform-origin: bottom center; }

  .tv-body {
    display: flex;
    flex: 1;
    min-height: 0;
    background: linear-gradient(145deg, #3a3530, #2a2520, #1e1a16);
    border: 3px solid #4a4035;
    border-radius: 16px 16px 12px 12px;
    padding: 12px;
    gap: 10px;
    box-shadow:
      0 6px 20px rgba(0, 0, 0, 0.5),
      inset 0 1px 0 rgba(255, 255, 255, 0.08);
  }

  .tv-screen-area {
    flex: 1;
    min-width: 0;
  }

  .tv-screen {
    position: relative;
    background: #111;
    /* aspect-ratio set via inline style from project resolution */
    border-radius: 10px;
    overflow: hidden;
    border: 3px solid #222;
    box-shadow:
      inset 0 0 30px rgba(0, 0, 0, 0.8),
      0 0 4px rgba(100, 200, 255, 0.1);
  }

  .tv-screen-inner {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }

  .tv-screen-inner video {
    width: 100%;
    height: 100%;
    object-fit: contain;
    border-radius: 6px;
  }

  .tv-static {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    width: 100%;
    height: 100%;
    color: #888;
    font-size: 11px;
    font-family: monospace;
    background:
      repeating-linear-gradient(
        0deg,
        transparent,
        transparent 1px,
        rgba(50, 50, 50, 0.3) 1px,
        rgba(50, 50, 50, 0.3) 2px
      );
  }
  .tv-static.error { color: var(--error); }
  .tv-static small { font-size: 9px; max-width: 140px; text-align: center; }

  .tv-no-signal {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.15em;
    color: #666;
    animation: flicker 3s infinite;
  }

  @keyframes flicker {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
    75% { opacity: 0.9; }
  }

  .tv-controls {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    width: 44px;
    flex-shrink: 0;
    padding-top: 4px;
  }

  .tv-label {
    font-size: 10px;
    font-weight: 700;
    color: #998877;
    font-family: monospace;
    letter-spacing: 0.05em;
    white-space: nowrap;
  }

  .tv-knob {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: radial-gradient(circle at 35% 35%, #666, #333);
    border: 2px solid #555;
    box-shadow:
      0 2px 4px rgba(0, 0, 0, 0.4),
      inset 0 1px 2px rgba(255, 255, 255, 0.1);
  }
  .tv-duration {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
  }

  .tv-duration-input {
    width: 38px;
    text-align: center;
    font-family: monospace;
    font-size: 11px;
    padding: 2px;
    color: #cba;
    background: #1a1510;
    border: 1px solid #555;
    border-radius: 4px;
  }

  .tv-duration-label {
    font-size: 8px;
    color: #776655;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .tv-lock-btn {
    background: transparent;
    color: #776655;
    border: none;
    padding: 4px;
    border-radius: 50%;
    cursor: pointer;
    transition: color 0.15s;
  }
  .tv-lock-btn:hover { color: var(--warning); }

  .tv-footer {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 0 0 var(--radius-lg) var(--radius-lg);
    overflow: hidden;
  }
  .tv-footer.locked { opacity: 0.7; }

  /* ── Locked state ── */
  .tl-card.locked {
    border-color: var(--locked);
    opacity: 0.85;
  }
  .tl-card.locked .tl-header { background: var(--locked-bg); }

  :global(.lock-indicator) { color: var(--locked); }
  :global(.combine-indicator) { color: var(--accent); }
  .btn-combine { color: var(--accent) !important; }
  .btn-combine:hover:not(:disabled) { background: var(--accent-bg) !important; }

  .spinner-container, .error-container, .placeholder-box {
    display: flex; flex-direction: column; align-items: center;
    gap: 5px; color: var(--text-muted); font-size: 12px;
  }
  .spinner {
    width: 22px; height: 22px; border: 3px solid var(--border);
    border-top-color: var(--accent); border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .error-container small {
    max-width: 160px; text-align: center; word-break: break-word; color: var(--error);
  }

  .render-placeholder {
    width: 100%; height: 100%;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 5px; color: var(--text-muted); font-size: 12px;
  }
  .render-placeholder.error { color: var(--error); }
  .render-placeholder small { font-size: 10px; max-width: 160px; text-align: center; }

  /* ── Body / prompts ── */
  .tl-body { padding: 8px 10px; }

  .prompt-text {
    font-size: 11px; color: var(--text-dim); line-height: 1.4;
    display: -webkit-box; -webkit-line-clamp: 3;
    -webkit-box-orient: vertical; overflow: hidden;
  }
  .prompt-text.clickable { cursor: pointer; transition: color 0.15s; }
  .prompt-text.clickable:hover { color: var(--text); }
  .prompt-text.empty { font-style: italic; color: var(--text-muted); }

  .edit-textarea { width: 100%; resize: vertical; font-size: 11px; min-height: 40px; }
  .edit-actions { display: flex; gap: 4px; margin-top: 4px; }

  .btn-save {
    background: var(--accent); color: white; font-size: 11px;
    padding: 3px 10px; display: inline-flex; align-items: center; gap: 3px;
  }
  .btn-cancel {
    background: transparent; color: var(--text-dim); border: 1px solid var(--border);
    font-size: 11px; padding: 3px 10px; display: inline-flex; align-items: center; gap: 3px;
  }

  .neg-edit { margin-top: 6px; padding-top: 6px; border-top: 1px solid var(--border); }
  .neg-label { font-size: 9px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--error); display: block; margin-bottom: 3px; }
  .neg-display { margin-top: 4px; font-size: 10px; color: var(--text-muted); line-height: 1.3; }
  .neg-label-inline { font-size: 10px; color: var(--error); }

  .rewrite-edit { margin-top: 6px; padding-top: 6px; border-top: 1px solid var(--border); }
  .rewrite-label { font-size: 9px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--accent); display: block; margin-bottom: 3px; }

  /* ── Actions row ── */
  .tl-actions {
    display: flex; flex-wrap: wrap; gap: 2px;
    padding: 5px 10px; border-top: 1px solid var(--border); align-items: center;
  }

  .btn-icon {
    background: transparent; color: var(--text-dim);
    padding: 4px 7px; font-size: 13px; border-radius: var(--radius);
  }
  .btn-icon:hover:not(:disabled) { background: var(--bg-card-hover); color: var(--text); }
  .btn-danger:hover:not(:disabled) { color: var(--error); }
  .btn-active { color: var(--warning); }
  .hidden-input { display: none; }

  .btn-render {
    background: var(--accent); color: white; font-size: 11px;
    padding: 3px 10px; margin-left: auto;
  }
  .btn-render:hover { background: var(--accent-hover); }

  /* ── Add button at end ── */
  .tl-add-btn {
    width: 60px; flex-shrink: 0; align-self: stretch;
    background: transparent; border: 2px dashed var(--border);
    border-radius: var(--radius-lg); color: var(--text-muted);
    display: flex; align-items: center; justify-content: center;
    cursor: pointer; transition: all 0.15s; min-height: 120px;
  }
  .tl-add-btn:hover { border-color: var(--accent); color: var(--accent); }

  /* ── Toolbar ── */
  .toolbar-btn {
    background: transparent; color: var(--text-muted);
    border: 1px solid var(--border); font-size: 12px;
    padding: 5px 12px; display: inline-flex; align-items: center; gap: 4px;
  }
  .toolbar-btn:hover:not(:disabled) { color: var(--text-dim); border-color: var(--text-muted); }

  /* ── Empty states ── */
  .empty-panel {
    text-align: center; padding: 60px 16px; color: var(--text-muted);
    border: 2px dashed var(--border); border-radius: var(--radius-lg);
  }
  .empty-panel p { font-size: 14px; }

  .empty-state {
    text-align: center; padding: 80px 20px; color: var(--text-muted);
    border: 2px dashed var(--border); border-radius: var(--radius-lg);
    display: flex; flex-direction: column; align-items: center; gap: 16px;
  }
  .empty-state p { font-size: 16px; }

  /* ── Blank keyframe options ── */
  .blank-kf-options {
    width: 100%; height: 100%;
    display: flex; align-items: center; justify-content: center;
    gap: 24px;
  }

  .gallery-placeholder, .derive-placeholder {
    display: flex; flex-direction: column; align-items: center;
    gap: 4px; cursor: pointer; color: var(--text-muted);
    transition: color 0.15s; padding: 12px;
    border-radius: var(--radius); border: 1px dashed var(--border);
  }
  .gallery-placeholder:hover { color: var(--accent); border-color: var(--accent); }
  .derive-placeholder:hover { color: var(--accent); border-color: var(--accent); }

  /* ── Gallery picker modal ── */
  .picker-overlay {
    position: fixed; inset: 0; background: rgba(0, 0, 0, 0.7);
    display: flex; align-items: center; justify-content: center; z-index: 2000;
  }
  .picker-modal {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: var(--radius-lg); padding: 24px;
    max-width: 700px; max-height: 80vh; overflow-y: auto; width: 90%;
  }
  .picker-modal.narrow { max-width: 420px; }
  .picker-modal h3 { font-size: 16px; margin-bottom: 16px; }
  .picker-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 10px; margin-bottom: 16px;
  }
  .picker-item {
    cursor: pointer; border: 2px solid transparent;
    border-radius: var(--radius); overflow: hidden; transition: border-color 0.15s;
  }
  .picker-item:hover { border-color: var(--accent); }
  .picker-item img { width: 100%; aspect-ratio: 1; object-fit: cover; display: block; }
  .picker-prompt {
    font-size: 10px; color: var(--text-muted); padding: 4px 6px;
    line-height: 1.3; display: -webkit-box; -webkit-line-clamp: 2;
    -webkit-box-orient: vertical; overflow: hidden;
  }
  .picker-cancel {
    background: transparent; border: 1px solid var(--border);
    color: var(--text-muted); padding: 6px 16px; border-radius: var(--radius); cursor: pointer;
  }
  .picker-cancel:hover { border-color: var(--text-muted); }

  /* ── Merge sequence picker ── */
  .merge-hint {
    font-size: 13px; color: var(--text-muted); margin-bottom: 16px; line-height: 1.4;
  }
  .merge-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px; }
  .merge-item {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 14px; background: var(--bg-input); border: 1px solid var(--border);
    border-radius: var(--radius); cursor: pointer; transition: all 0.15s;
  }
  .merge-item:hover { border-color: var(--accent); background: var(--bg-card-hover); }
  .merge-name { font-size: 14px; font-weight: 500; color: var(--text); }
  .merge-count { font-size: 12px; color: var(--text-muted); }
</style>
