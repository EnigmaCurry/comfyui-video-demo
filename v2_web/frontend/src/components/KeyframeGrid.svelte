<script>
  import { flip } from 'svelte/animate';
  import { dndzone } from 'svelte-dnd-action';
  import { RotateCcw } from 'lucide-svelte';
  import KeyframeCard from './KeyframeCard.svelte';
  import { reorderKeyframes, renderKeyframe, setActiveIndex, resetKeyframes } from '../lib/api.js';

  let { keyframes = $bindable([]), projectId = '', onupdated, onstatus, onreset } = $props();

  let activeIndex = $state(-1);
  let initialized = $state(false);

  const flipDurationMs = 200;

  export function setActive(idx) {
    activeIndex = idx;
    initialized = true;
  }

  // Auto-set activeIndex on first load based on keyframe statuses
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
    const deletedIdx = keyframes.findIndex(kf => kf.id === id);
    keyframes = keyframes.filter(kf => kf.id !== id);
    if (deletedIdx <= activeIndex && activeIndex > 0) {
      activeIndex--;
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
</script>

{#if keyframes.length > 0}
  <div class="toolbar">
    <button class="reset-btn" onclick={handleReset}>
      <RotateCcw size={14} /> Reset
    </button>
  </div>
  <div class="grid"
       use:dndzone={{ items: keyframes, flipDurationMs, type: 'keyframes' }}
       onconsider={handleDndConsider}
       onfinalize={handleDndFinalize}>
    {#each keyframes as kf, i (kf.id)}
      <div class="grid-item" animate:flip={{ duration: flipDurationMs }}>
        <KeyframeCard
          keyframe={kf}
          index={i}
          active={i === activeIndex}
          {projectId}
          {onstatus}
          {onupdated}
          ondelete={handleDelete}
          onapprove={handleApprove}
        />
      </div>
    {/each}
  </div>
{:else}
  <div class="empty">
    <p>No keyframes yet. Enter a theme above and click Generate.</p>
  </div>
{/if}

<style>
  .toolbar {
    display: flex;
    justify-content: flex-end;
    margin-bottom: 12px;
  }

  .reset-btn {
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border);
    font-size: 13px;
    padding: 6px 14px;
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }

  .reset-btn:hover {
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
