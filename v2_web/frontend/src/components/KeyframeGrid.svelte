<script>
  import { flip } from 'svelte/animate';
  import { dndzone } from 'svelte-dnd-action';
  import KeyframeCard from './KeyframeCard.svelte';
  import { reorderKeyframes, renderKeyframe } from '../lib/api.js';

  let { keyframes = $bindable([]), onupdated, onstatus } = $props();

  // Index of the card currently being reviewed (has the approve button)
  let activeIndex = $state(0);

  const flipDurationMs = 200;

  // Reset active index when keyframes are replaced (new generation)
  let prevLength = $state(0);
  $effect(() => {
    if (keyframes.length > 0 && keyframes.length !== prevLength) {
      // Only reset if this looks like a fresh generation (went from 0 or changed count)
      if (prevLength === 0) {
        activeIndex = 0;
      }
      prevLength = keyframes.length;
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
    // Adjust activeIndex if needed
    if (deletedIdx <= activeIndex && activeIndex > 0) {
      activeIndex--;
    }
  }

  async function handleApprove(event) {
    const nextIndex = activeIndex + 1;
    if (nextIndex < keyframes.length) {
      activeIndex = nextIndex;
      const nextKf = keyframes[nextIndex];
      // Render the next keyframe
      if (nextKf.status === 'pending') {
        onstatus({ detail: `Approved #${activeIndex}. Rendering #${nextIndex + 1}...` });
        try {
          const result = await renderKeyframe(nextKf.id);
          nextKf.status = result.status;
        } catch (e) {
          onstatus({ detail: `Render error: ${e.message}` });
        }
      } else {
        onstatus({ detail: `Approved #${activeIndex}. Reviewing #${nextIndex + 1}...` });
      }
    } else {
      onstatus({ detail: 'All keyframes approved!' });
      activeIndex = keyframes.length; // no active card
    }
  }
</script>

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
          active={i === activeIndex}
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
