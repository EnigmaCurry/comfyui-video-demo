<script>
  import { flip } from 'svelte/animate';
  import { dndzone } from 'svelte-dnd-action';
  import KeyframeCard from './KeyframeCard.svelte';
  import { reorderKeyframes } from '../lib/api.js';

  let { keyframes = $bindable([]), onupdated, onstatus } = $props();

  const flipDurationMs = 200;

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
          {onstatus}
          {onupdated}
          ondelete={handleDelete}
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
