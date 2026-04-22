<script>
  import { flip } from 'svelte/animate';
  import { dndzone } from 'svelte-dnd-action';
  import { RotateCcw, Zap, ArrowRight, Plus } from 'lucide-svelte';
  import KeyframeCard from './KeyframeCard.svelte';
  import { reorderKeyframes, resetKeyframes,
           autoCreateKeyframes, getKeyframeStatus,
           addKeyframe, syncTransitions, setResolution, RESOLUTIONS } from '../lib/api.js';

  let { keyframes = $bindable([]), projectId = '',
        projectWidth = 1024, projectHeight = 576,
        onupdated, onstatus, onreset, ongotransitions, onsync } = $props();

  let autoCreating = $state(false);
  let syncing = $state(false);

  const flipDurationMs = 200;

  let allDone = $derived(keyframes.length > 0 && keyframes.every(kf => kf.status === 'done'));
  let hasDonePairs = $derived(() => {
    for (let i = 0; i < keyframes.length - 1; i++) {
      if (keyframes[i].status === 'done' && keyframes[i + 1].status === 'done') return true;
    }
    return false;
  });

  function handleDndConsider(e) {
    keyframes = e.detail.items;
  }

  async function handleDndFinalize(e) {
    keyframes = e.detail.items;
    try {
      const ids = keyframes.map(kf => kf.id);
      await reorderKeyframes(ids);
    } catch (err) {
      onstatus({ detail: `Reorder failed: ${err.message}` });
    }
  }

  function handleDelete(event) {
    const id = event.detail;
    keyframes = keyframes.filter(kf => kf.id !== id);
  }

  function handleDuplicate(event) {
    keyframes = event.detail;
  }

  async function handleAdd() {
    try {
      const kf = await addKeyframe();
      keyframes = [...keyframes, kf];
      onstatus({ detail: `Added keyframe ${keyframes.length}. Drag to reorder.` });
    } catch (e) {
      onstatus({ detail: `Failed: ${e.message}` });
    }
  }

  async function handleReset() {
    if (!confirm('Reset all keyframes to the original story? All renders and edits will be lost.')) return;
    onstatus({ detail: 'Resetting keyframes...' });
    try {
      const data = await resetKeyframes();
      if (onreset) onreset({ detail: data.project });
      onstatus({ detail: 'Keyframes reset to original story.' });
    } catch (e) {
      onstatus({ detail: `Reset failed: ${e.message}` });
    }
  }

  async function handleAutoCreate() {
    if (!confirm('Render all remaining keyframes automatically?')) return;
    autoCreating = true;
    onstatus({ detail: 'Auto-creating all keyframes...' });
    try {
      const data = await autoCreateKeyframes();
      onstatus({ detail: `Auto-creating ${data.started} keyframes...` });
      await pollAllKeyframes();
      onstatus({ detail: 'All keyframes auto-created!' });
    } catch (e) {
      onstatus({ detail: `Auto-create failed: ${e.message}` });
    } finally {
      autoCreating = false;
    }
  }

  async function pollAllKeyframes() {
    while (keyframes.some(kf => kf.status === 'pending' || kf.status === 'rendering')) {
      await new Promise(r => setTimeout(r, 2000));
      for (const kf of keyframes) {
        if (kf.status === 'rendering' || kf.status === 'pending') {
          try {
            const status = await getKeyframeStatus(kf.id);
            kf.status = status.status;
            kf.error_message = status.error_message;
            if (status.seed != null) kf.seed = status.seed;
            if (status.image_url) {
              kf.image_filename = status.image_url.split('/').pop();
            }
          } catch {}
        }
      }
    }
  }

  async function handleResolutionChange(e) {
    const r = RESOLUTIONS[e.target.selectedIndex];
    try {
      await setResolution(r.w, r.h);
      onstatus({ detail: `Resolution set to ${r.w}×${r.h}. New renders will use this size.` });
    } catch (err) {
      onstatus({ detail: `Failed: ${err.message}` });
    }
  }

  async function handleGoToTransitions() {
    syncing = true;
    onstatus({ detail: 'Syncing transitions...' });
    try {
      const data = await syncTransitions();
      if (ongotransitions) ongotransitions({ detail: data.project });
      onstatus({ detail: 'Transitions synced.' });
    } catch (e) {
      onstatus({ detail: `Failed: ${e.message}` });
    } finally {
      syncing = false;
    }
  }
</script>

<div class="toolbar">
  <button class="toolbar-btn" onclick={handleAdd}>
    <Plus size={14} /> Add
  </button>
  {#if keyframes.length > 0}
    <button class="toolbar-btn" onclick={handleReset}>
      <RotateCcw size={14} /> Reset
    </button>
    <button class="toolbar-btn" onclick={handleAutoCreate} disabled={autoCreating || allDone}>
      <Zap size={14} /> {autoCreating ? 'Creating...' : 'Auto Create'}
    </button>
  {/if}
  <select class="res-select" onchange={handleResolutionChange}>
    {#each RESOLUTIONS as r}
      <option selected={r.w === projectWidth && r.h === projectHeight}>{r.label}</option>
    {/each}
  </select>
</div>

{#if keyframes.length > 0}
  <div class="grid"
       use:dndzone={{ items: keyframes, flipDurationMs, type: 'keyframes' }}
       onconsider={handleDndConsider}
       onfinalize={handleDndFinalize}>
    {#each keyframes as kf, i (kf.id)}
      <div class="grid-item" animate:flip={{ duration: flipDurationMs }}>
        <KeyframeCard
          keyframe={kf}
          index={i}
          {projectId}
          {onstatus}
          {onupdated}
          ondelete={handleDelete}
          onduplicate={handleDuplicate}
        />
      </div>
    {/each}
  </div>

  {#if allDone}
    <div class="all-done">
      <span>All keyframes ready!</span>
      <button class="go-btn" onclick={handleGoToTransitions} disabled={syncing}>
        {syncing ? 'Syncing transitions...' : 'Go to Transitions'} <ArrowRight size={16} />
      </button>
    </div>
  {/if}
{:else}
  <div class="empty">
    <p>No keyframes yet. Click Add to create one.</p>
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

  .res-select {
    margin-left: auto;
    font-family: inherit;
    font-size: 13px;
    color: var(--text-dim);
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 6px 10px;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }

  .grid-item {
    min-width: 0;
  }

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

  .all-done span {
    font-size: 16px;
    font-weight: 500;
    color: var(--success);
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

  .go-btn:hover:not(:disabled) {
    background: var(--accent-hover);
  }

  .empty {
    text-align: center;
    padding: 80px 20px;
    color: var(--text-muted);
    border: 2px dashed var(--border);
    border-radius: var(--radius-lg);
    margin-bottom: 24px;
  }

  .empty p {
    font-size: 16px;
  }
</style>
