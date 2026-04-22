<script>
  import { Copy, Trash2, Plus, RefreshCw, ChevronLeft, ChevronRight, Pencil, Combine } from 'lucide-svelte';
  import { galleryList, galleryDelete, galleryUpload } from '../lib/api.js';

  let { projectId = '', onstatus, oncreate, onrecreate, onedit, onklein } = $props();

  let images = $state([]);
  let loading = $state(true);

  async function fetchImages() {
    loading = true;
    try {
      const data = await galleryList();
      images = data.images;
    } catch (e) {
      onstatus?.({ detail: `Failed to load gallery: ${e.message}` });
    } finally {
      loading = false;
    }
  }

  async function handleDelete(img) {
    if (!confirm('Delete this image?')) return;
    try {
      await galleryDelete(img.id);
      images = images.filter(i => i.id !== img.id);
      onstatus?.({ detail: 'Image deleted.' });
    } catch (e) {
      onstatus?.({ detail: `Delete failed: ${e.message}` });
    }
  }

  async function handleCopy(img) {
    try {
      const resp = await fetch(img.image_url);
      const blob = await resp.blob();
      const pngBlob = blob.type === 'image/png' ? blob : await convertToPng(blob);
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': pngBlob })]);
      onstatus?.({ detail: 'Image copied to clipboard.' });
    } catch (e) {
      onstatus?.({ detail: `Copy failed: ${e.message}` });
    }
  }

  function convertToPng(blob) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = img.width;
        canvas.height = img.height;
        canvas.getContext('2d').drawImage(img, 0, 0);
        canvas.toBlob(b => b ? resolve(b) : reject(new Error('Conversion failed')), 'image/png');
      };
      img.onerror = reject;
      img.src = URL.createObjectURL(blob);
    });
  }

  let fullscreenIndex = $state(-1);
  let fullscreenImg = $derived(fullscreenIndex >= 0 ? images[fullscreenIndex] : null);

  function openFullscreen(idx) { fullscreenIndex = idx; }
  function closeFullscreen() { fullscreenIndex = -1; }
  function prevImage(e) { e.stopPropagation(); if (fullscreenIndex > 0) fullscreenIndex--; }
  function nextImage(e) { e.stopPropagation(); if (fullscreenIndex < images.length - 1) fullscreenIndex++; }

  function handleFullscreenKey(e) {
    if (fullscreenIndex < 0) return;
    if (e.key === 'ArrowLeft') prevImage(e);
    else if (e.key === 'ArrowRight') nextImage(e);
    else if (e.key === 'Escape') closeFullscreen();
    else if (e.key === 'c' && (e.ctrlKey || e.metaKey) && fullscreenImg) {
      e.preventDefault();
      handleCopy(fullscreenImg);
    }
  }

  async function handlePaste(e) {
    if (fullscreenIndex >= 0) return; // don't paste while in fullscreen
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        e.preventDefault();
        const blob = item.getAsFile();
        if (!blob) continue;
        onstatus?.({ detail: 'Uploading pasted image...' });
        try {
          const data = await galleryUpload(blob);
          images = [...images, data.image];
          onstatus?.({ detail: 'Image uploaded to gallery.' });
        } catch (err) {
          onstatus?.({ detail: `Upload failed: ${err.message}` });
        }
        return;
      }
    }
  }

  // Fetch on mount and when projectId changes
  $effect(() => {
    if (projectId) fetchImages();
  });
</script>

<svelte:window onkeydown={handleFullscreenKey} onpaste={handlePaste} />

{#if fullscreenImg}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="fullscreen-overlay" onclick={closeFullscreen}>
    {#if fullscreenIndex > 0}
      <button class="nav-btn nav-left" onclick={prevImage}>
        <ChevronLeft size={36} />
      </button>
    {/if}
    <img src={fullscreenImg.image_url} alt="Full size" />
    {#if fullscreenIndex < images.length - 1}
      <button class="nav-btn nav-right" onclick={nextImage}>
        <ChevronRight size={36} />
      </button>
    {/if}
  </div>
{/if}

<div class="gallery-page">
  {#if loading}
    <p class="status-text">Loading...</p>
  {:else if images.length === 0}
    <div class="empty">
      <p>No saved images yet.</p>
      <button class="create-btn" onclick={() => oncreate?.()}>
        <Plus size={16} /> Create your first image
      </button>
    </div>
  {:else}
    <div class="gallery-grid">
      {#each images as img, idx (img.id)}
        <div class="gallery-item">
          {#if img.image_url}
            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
            <div class="image-wrap" onclick={() => openFullscreen(idx)}>
              <img src={img.image_url} alt={img.prompt} />
            </div>
          {:else}
            <div class="image-placeholder">
              <span>No image</span>
            </div>
          {/if}
          <div class="item-footer">
            <p class="item-prompt">{img.prompt}</p>
            <div class="item-meta">
              <span>{img.width}x{img.height}</span>
              <span>{img.model}</span>
            </div>
            <div class="item-actions">
              <button class="icon-btn" onclick={() => onedit?.({ detail: img })} title="Edit with filters">
                <Pencil size={14} />
              </button>
              <button class="icon-btn" onclick={() => onrecreate?.({ detail: img })} title="Recreate in generator">
                <RefreshCw size={14} />
              </button>
              <button class="icon-btn" onclick={() => onklein?.({ detail: img })} title="Combine with Klein">
                <Combine size={14} />
              </button>
              <button class="icon-btn" onclick={() => handleCopy(img)} title="Copy to clipboard">
                <Copy size={14} />
              </button>
              <button class="icon-btn danger" onclick={() => handleDelete(img)} title="Delete">
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

  .status-text {
    text-align: center;
    padding: 48px 20px;
    color: var(--text-muted);
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
    overflow: hidden;
  }

  .image-wrap img {
    width: 100%;
    display: block;
    transition: transform 0.15s ease;
  }

  .image-wrap:hover img { transform: scale(1.03); }

  .image-placeholder {
    aspect-ratio: 16 / 9;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    font-size: 13px;
    background: var(--bg-input);
  }

  .item-footer {
    padding: 10px 12px;
  }

  .item-prompt {
    font-size: 13px;
    color: var(--text-dim);
    line-height: 1.4;
    margin-bottom: 6px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .item-meta {
    display: flex;
    gap: 8px;
    font-size: 11px;
    color: var(--text-muted);
    margin-bottom: 6px;
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
    max-width: 85vw;
    max-height: 95vh;
    object-fit: contain;
  }

  .nav-btn {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    background: rgba(0, 0, 0, 0.5);
    color: white;
    border: none;
    border-radius: 50%;
    width: 56px;
    height: 56px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    opacity: 0.6;
    transition: opacity 0.15s;
    z-index: 2001;
  }

  .nav-btn:hover { opacity: 1; }
  .nav-btn.nav-left { left: 24px; }
  .nav-btn.nav-right { right: 24px; }
</style>
