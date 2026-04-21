<script>
  import { RefreshCw, Trash2, Plus } from 'lucide-svelte';
  import { getKeyframeStatus, rerenderKeyframe, deleteKeyframe } from '../lib/api.js';

  let { keyframes = $bindable([]), projectId = '', onstatus, oncreate } = $props();

  let pollingIds = $state(new Set());

  function imageUrl(kf) {
    if (!kf.image_filename) return null;
    return `/api/projects/${projectId}/images/${kf.image_filename}`;
  }

  async function pollStatus(kfId) {
    if (pollingIds.has(kfId)) return;
    pollingIds.add(kfId);
    pollingIds = new Set(pollingIds);
    try {
      while (true) {
        const data = await getKeyframeStatus(kfId);
        const kf = keyframes.find(k => k.id === kfId);
        if (!kf) break;
        kf.status = data.status;
        if (data.image_filename) kf.image_filename = data.image_filename;
        if (data.error_message) kf.error_message = data.error_message;
        keyframes = [...keyframes];
        if (data.status === 'done' || data.status === 'error') break;
        await new Promise(r => setTimeout(r, 2000));
      }
    } finally {
      pollingIds.delete(kfId);
      pollingIds = new Set(pollingIds);
    }
  }

  // Start polling for any rendering keyframes
  $effect(() => {
    for (const kf of keyframes) {
      if (kf.status === 'rendering' && !pollingIds.has(kf.id)) {
        pollStatus(kf.id);
      }
    }
  });

  async function handleRerender(kf) {
    kf.status = 'rendering';
    keyframes = [...keyframes];
    onstatus?.({ detail: 'Re-generating image...' });
    try {
      await rerenderKeyframe(kf.id);
    } catch (e) {
      onstatus?.({ detail: `Render error: ${e.message}` });
    }
  }

  async function handleDelete(kf) {
    if (!confirm('Delete this image?')) return;
    try {
      await deleteKeyframe(kf.id);
      keyframes = keyframes.filter(k => k.id !== kf.id);
      onstatus?.({ detail: 'Image deleted.' });
    } catch (e) {
      onstatus?.({ detail: `Delete failed: ${e.message}` });
    }
  }

  let fullscreenUrl = $state(null);
</script>

{#if fullscreenUrl}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="fullscreen-overlay" onclick={() => fullscreenUrl = null}>
    <img src={fullscreenUrl} alt="Full size" />
  </div>
{/if}

<div class="gallery-page">
  {#if keyframes.length === 0}
    <div class="empty">
      <p>No images yet.</p>
      <button class="create-btn" onclick={() => oncreate?.()}>
        <Plus size={16} /> Create your first image
      </button>
    </div>
  {:else}
    <div class="gallery-grid">
      {#each [...keyframes].reverse() as kf (kf.id)}
        <div class="gallery-item">
          {#if kf.status === 'rendering'}
            <div class="image-placeholder">
              <div class="spinner"></div>
              <span>Generating...</span>
            </div>
          {:else if kf.status === 'error'}
            <div class="image-placeholder error">
              <span>Error: {kf.error_message || 'Unknown'}</span>
            </div>
          {:else if imageUrl(kf)}
            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
            <div class="image-wrap" onclick={() => fullscreenUrl = imageUrl(kf)}>
              <img src={imageUrl(kf)} alt={kf.prompt} />
            </div>
          {:else}
            <div class="image-placeholder">
              <span>No image</span>
            </div>
          {/if}
          <div class="item-footer">
            <p class="item-prompt">{kf.prompt}</p>
            <div class="item-actions">
              <button class="icon-btn" onclick={() => handleRerender(kf)} title="Re-generate">
                <RefreshCw size={14} />
              </button>
              <button class="icon-btn danger" onclick={() => handleDelete(kf)} title="Delete">
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .gallery-page {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 28px;
  }

  .empty {
    text-align: center;
    padding: 48px 20px;
    color: var(--text-muted);
  }

  .create-btn {
    margin-top: 16px;
    background: var(--accent);
    color: white;
    font-weight: 500;
    padding: 10px 24px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }

  .create-btn:hover { background: var(--accent-hover); }

  .gallery-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 20px;
  }

  .gallery-item {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    background: var(--bg);
  }

  .image-wrap {
    cursor: pointer;
    aspect-ratio: 16 / 9;
    overflow: hidden;
  }

  .image-wrap img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    transition: transform 0.15s ease;
  }

  .image-wrap:hover img { transform: scale(1.03); }

  .image-placeholder {
    aspect-ratio: 16 / 9;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    color: var(--text-muted);
    font-size: 13px;
    background: var(--bg-input);
  }

  .image-placeholder.error { color: var(--error); }

  .spinner {
    width: 24px;
    height: 24px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  .item-footer {
    padding: 10px 12px;
  }

  .item-prompt {
    font-size: 13px;
    color: var(--text-dim);
    line-height: 1.4;
    margin-bottom: 8px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .item-actions {
    display: flex;
    gap: 4px;
  }

  .icon-btn {
    background: transparent;
    color: var(--text-muted);
    padding: 4px 6px;
    font-size: 12px;
  }

  .icon-btn:hover { color: var(--text); }
  .icon-btn.danger:hover { color: var(--error); }

  .fullscreen-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.9);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 2000;
    cursor: pointer;
  }

  .fullscreen-overlay img {
    max-width: 95vw;
    max-height: 95vh;
    object-fit: contain;
  }
</style>
