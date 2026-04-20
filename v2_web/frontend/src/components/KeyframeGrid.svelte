<script>
  import { flip } from 'svelte/animate';
  import { dndzone } from 'svelte-dnd-action';
  import { RotateCcw, Zap, ArrowRight } from 'lucide-svelte';
  import KeyframeCard from './KeyframeCard.svelte';
  import { reorderKeyframes, renderKeyframe, setActiveIndex, resetKeyframes,
           lockKeyframes, autoCreateKeyframes } from '../lib/api.js';

  let { keyframes = $bindable([]), projectId = '', locked = false,
        onupdated, onstatus, onreset, onlockkeyframes } = $props();

  let activeIndex = $state(-1);
  let initialized = $state(false);
  let autoCreating = $state(false);
  let locking = $state(false);

  const flipDurationMs = 200;

  export function setActive(idx) {
    activeIndex = idx;
    initialized = true;
  }

  $effect(() => {
    if (initialized || keyframes.length === 0) return;
    initialized = true;
    const firstPending = keyframes.findIndex(kf => kf.status === 'pending');
    if (firstPending === -1) {
      activeIndex = keyframes.length - 1;
    } else if (firstPending === 0) {
      activeIndex = 0;
    } else {
      activeIndex = firstPending - 1;
    }
  });

  let allDone = $derived(keyframes.length > 0 && keyframes.every(kf => kf.status === 'done'));

  function handleDndConsider(e) {
    if (locked) return;
    keyframes = e.detail.items;
  }

  async function handleDndFinalize(e) {
    if (locked) return;
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
    const deletedIdx = keyframes.findIndex(kf => kf.id === id);
    keyframes = keyframes.filter(kf => kf.id !== id);
    if (deletedIdx <= activeIndex && activeIndex > 0) {
      activeIndex--;
      setActiveIndex(activeIndex);
    }
  }

  async function handleApprove(event) {
    const nextIndex = activeIndex + 1;
    if (nextIndex < keyframes.length) {
      activeIndex = nextIndex;
      setActiveIndex(activeIndex);
      const nextKf = keyframes[nextIndex];
      if (nextKf.status === 'pending') {
        onstatus({ detail: `Approved #${activeIndex}. Rendering #${nextIndex + 1}...` });
        nextKf.status = 'rendering';
        try {
          await renderKeyframe(nextKf.id);
        } catch (e) {
          onstatus({ detail: `Render error: ${e.message}` });
        }
      } else {
        onstatus({ detail: `Approved #${activeIndex}. Reviewing #${nextIndex + 1}...` });
      }
    } else {
      onstatus({ detail: 'All keyframes approved!' });
      activeIndex = keyframes.length;
      setActiveIndex(activeIndex);
    }
  }

  async function handleReset() {
    if (!confirm('Reset all keyframes to the original story? All renders and edits will be lost.')) return;
    onstatus({ detail: 'Resetting keyframes...' });
    try {
      const data = await resetKeyframes();
      if (onreset) onreset({ detail: data.project });
      onstatus({ detail: 'Keyframes reset to original story.' });
      initialized = false;
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
      if (onreset) onreset({ detail: data.project });
      onstatus({ detail: `Auto-created ${data.rendered} keyframes. All done!` });
      initialized = false;
    } catch (e) {
      onstatus({ detail: `Auto-create failed: ${e.message}` });
    } finally {
      autoCreating = false;
    }
  }

  async function handleGoToTransitions() {
    locking = true;
    onstatus({ detail: 'Locking keyframes and generating transition descriptions...' });
    try {
      const data = await lockKeyframes();
      if (onlockkeyframes) onlockkeyframes({ detail: data.project });
      onstatus({ detail: 'Keyframes locked. Proceed to Transitions.' });
    } catch (e) {
      onstatus({ detail: `Failed: ${e.message}` });
    } finally {
      locking = false;
    }
  }
</script>

{#if keyframes.length > 0}
  <div class="toolbar">
    {#if !locked}
      <button class="toolbar-btn" onclick={handleReset}>
        <RotateCcw size={14} /> Reset
      </button>
      <button class="toolbar-btn" onclick={handleAutoCreate} disabled={autoCreating || allDone}>
        <Zap size={14} /> {autoCreating ? 'Creating...' : 'Auto Create'}
      </button>
    {/if}
  </div>

  <div class="grid"
       use:dndzone={{ items: keyframes, flipDurationMs, type: 'keyframes', dragDisabled: locked }}
       onconsider={handleDndConsider}
       onfinalize={handleDndFinalize}>
    {#each keyframes as kf, i (kf.id)}
      <div class="grid-item" animate:flip={{ duration: flipDurationMs }}>
        <KeyframeCard
          keyframe={kf}
          index={i}
          active={!locked && i === activeIndex}
          {projectId}
          {onstatus}
          {onupdated}
          ondelete={handleDelete}
          onapprove={handleApprove}
        />
      </div>
    {/each}
  </div>

  {#if allDone && !locked}
    <div class="all-done">
      <span>All keyframes approved!</span>
      <button class="go-btn" onclick={handleGoToTransitions} disabled={locking}>
        {locking ? 'Generating transitions...' : 'Go to Transitions'} <ArrowRight size={16} />
      </button>
    </div>
  {/if}
{:else}
  <div class="empty">
    <p>No keyframes yet. Enter a theme above and click Generate.</p>
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
