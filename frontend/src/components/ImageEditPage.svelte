<script>
  import { X, ClipboardPaste, Save } from 'lucide-svelte';
  import { galleryFilter, galleryFilterStatus, galleryFilterSave, galleryUpload, galleryList, IMAGE_FILTERS } from '../lib/api.js';

  let { project = $bindable(null), onstatus, ongallery, editImage = $bindable(null) } = $props();

  let filter = $state('aspect_crop');
  let mirrorX = $state(true);
  let mirrorY = $state(true);
  let divisor = $state(2);
  let position = $state('C');
  let processing = $state(false);
  let saving = $state(false);

  const POSITIONS = [
    ['NW', 'N', 'NE'],
    ['W',  'C',  'E'],
    ['SW', 'S', 'SE'],
  ];

  // Aspect Crop state
  const ASPECT_RATIOS = ['16:9', '4:3', '1:1', '3:2', '9:16', 'Free'];
  let aspectRatio = $state('16:9');
  let cropCenterPx = $state(null);
  let cropRect = $state(null);
  let isDragging = $state(false);
  let cropCanvas = $state(null);
  let cropImg = $state(null);

  let isInteractive = $derived(IMAGE_FILTERS.find(f => f.id === filter)?.interactive || false);
  let showCropUI = $derived(filter === 'aspect_crop' && sourceUrl && !resultUrl && !processing);

  // Source image (pasted or picked from gallery)
  let sourceId = $state(null);
  let sourceUrl = $state(null);

  // Result
  let resultUrl = $state(null);
  let resultError = $state('');

  // Gallery picker
  let showGalleryPicker = $state(false);
  let galleryImages = $state([]);

  async function handlePaste(e) {
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
          project = data.project;
          sourceId = data.image.id;
          sourceUrl = data.image.image_url;
          onstatus?.({ detail: 'Image pasted.' });
        } catch (err) {
          onstatus?.({ detail: `Upload failed: ${err.message}` });
        }
        return;
      }
    }
  }

  async function openGalleryPicker() {
    try {
      const data = await galleryList();
      galleryImages = data.images.filter(i => i.image_url);
      showGalleryPicker = true;
    } catch (e) {
      onstatus?.({ detail: `Failed to load gallery: ${e.message}` });
    }
  }

  function pickImage(img) {
    sourceId = img.id;
    sourceUrl = img.image_url;
    showGalleryPicker = false;
  }

  let isSlow = $derived(IMAGE_FILTERS.find(f => f.id === filter)?.slow || false);

  // Auto-preview for instant filters when source or settings change
  $effect(() => {
    const sid = sourceId;
    const f = filter;
    const mx = mirrorX;
    const my = mirrorY;
    const d = divisor;
    const p = position;
    const filterDef = IMAGE_FILTERS.find(x => x.id === f);
    if (!sid || filterDef?.slow || filterDef?.interactive) return;
    runFilter(sid, f, mx, my, d, p);
  });

  async function handleRun() {
    if (!sourceId) return;
    runFilter(sourceId, filter, mirrorX, mirrorY, divisor, position);
  }

  async function runFilter(sid, f, mx, my, d, p, extra = {}) {
    processing = true;
    resultUrl = null;
    resultError = '';
    try {
      const data = await galleryFilter({
        source_id: sid, filter: f,
        mirror_x: mx, mirror_y: my,
        divisor: d, position: p,
        ...extra,
      });
      project = data.project;
      if (data.async) {
        // Poll for completion
        await pollFilterResult();
      } else {
        resultUrl = data.image_url;
        processing = false;
      }
    } catch (e) {
      resultError = e.message;
      processing = false;
    }
  }

  async function pollFilterResult() {
    const interval = setInterval(async () => {
      try {
        const data = await galleryFilterStatus();
        if (data.status === 'done') {
          clearInterval(interval);
          resultUrl = `${data.image_url}?t=${Date.now()}`;
          processing = false;
        } else if (data.status === 'error') {
          clearInterval(interval);
          resultError = data.error_message || 'Filter failed';
          processing = false;
        }
      } catch {
        // keep polling
      }
    }, 2000);
  }

  // Consume editImage prop from gallery
  $effect(() => {
    if (editImage) {
      const img = editImage;
      editImage = null;
      sourceId = img.id;
      sourceUrl = img.image_url;
    }
  });

  // --- Aspect Crop interactive handlers ---

  function handleCropImgLoad() {
    if (!cropImg || !cropCanvas) return;
    cropCanvas.width = cropImg.clientWidth;
    cropCanvas.height = cropImg.clientHeight;
    cropCenterPx = null;
    cropRect = null;
    drawCropOverlay();
  }

  function handleCropMouseDown(e) {
    if (!cropCanvas) return;
    e.preventDefault();
    const rect = cropCanvas.getBoundingClientRect();
    cropCenterPx = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    cropRect = null;
    isDragging = true;
    drawCropOverlay();
  }

  function handleCropMouseMove(e) {
    if (!isDragging || !cropCenterPx || !cropCanvas) return;
    e.preventDefault();
    const rect = cropCanvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    const dx = Math.abs(x - cropCenterPx.x);
    const dy = Math.abs(y - cropCenterPx.y);

    let halfW, halfH;
    if (aspectRatio === 'Free') {
      halfW = dx;
      halfH = dy;
    } else {
      const [arW, arH] = aspectRatio.split(':').map(Number);
      if (dx >= dy) {
        halfW = dx;
        halfH = dx * (arH / arW);
      } else {
        halfH = dy;
        halfW = dy * (arW / arH);
      }
    }

    cropRect = {
      x: cropCenterPx.x - halfW,
      y: cropCenterPx.y - halfH,
      w: halfW * 2,
      h: halfH * 2,
    };
    drawCropOverlay();
  }

  function handleCropMouseUp() {
    if (!isDragging) return;
    isDragging = false;

    if (!cropRect || !cropCanvas || cropRect.w < 5 || cropRect.h < 5) {
      cropRect = null;
      drawCropOverlay();
      return;
    }

    const cw = cropCanvas.width;
    const ch = cropCanvas.height;
    runFilter(sourceId, filter, mirrorX, mirrorY, divisor, position, {
      center_x: cropCenterPx.x / cw,
      center_y: cropCenterPx.y / ch,
      crop_w: cropRect.w / cw,
      crop_h: cropRect.h / ch,
    });
  }

  function drawCropOverlay() {
    if (!cropCanvas) return;
    const ctx = cropCanvas.getContext('2d');
    const w = cropCanvas.width;
    const h = cropCanvas.height;
    ctx.clearRect(0, 0, w, h);

    if (cropRect) {
      ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
      ctx.fillRect(0, 0, w, cropRect.y);
      ctx.fillRect(0, cropRect.y + cropRect.h, w, h - cropRect.y - cropRect.h);
      ctx.fillRect(0, cropRect.y, cropRect.x, cropRect.h);
      ctx.fillRect(cropRect.x + cropRect.w, cropRect.y, w - cropRect.x - cropRect.w, cropRect.h);

      ctx.strokeStyle = 'rgba(255, 255, 255, 0.9)';
      ctx.lineWidth = 2;
      ctx.strokeRect(cropRect.x, cropRect.y, cropRect.w, cropRect.h);
    }

    if (cropCenterPx) {
      ctx.strokeStyle = 'rgba(255, 100, 100, 0.8)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(cropCenterPx.x - 12, cropCenterPx.y);
      ctx.lineTo(cropCenterPx.x + 12, cropCenterPx.y);
      ctx.moveTo(cropCenterPx.x, cropCenterPx.y - 12);
      ctx.lineTo(cropCenterPx.x, cropCenterPx.y + 12);
      ctx.stroke();
    }
  }

  function handleRecrop() {
    resultUrl = null;
    resultError = '';
    cropCenterPx = null;
    cropRect = null;
  }

  function clearAll() {
    sourceId = null;
    sourceUrl = null;
    resultUrl = null;
    resultError = '';
    processing = false;
    saving = false;
    showGalleryPicker = false;
  }

  async function handleSave() {
    saving = true;
    try {
      const data = await galleryFilterSave();
      project = data.project;
      onstatus?.({ detail: 'Saved to gallery.' });
      clearAll();
      ongallery?.();
    } catch (e) {
      onstatus?.({ detail: `Save failed: ${e.message}` });
    } finally {
      saving = false;
    }
  }

  async function handleApplyToEditor() {
    // Save the preview to get a permanent ID, then use it as the new source
    saving = true;
    try {
      const data = await galleryFilterSave();
      project = data.project;
      sourceId = data.image.id;
      sourceUrl = data.image.image_url;
      resultUrl = null;
      resultError = '';
    } catch (e) {
      onstatus?.({ detail: `Apply failed: ${e.message}` });
    } finally {
      saving = false;
    }
  }
</script>

<svelte:window onpaste={handlePaste} />

{#if showGalleryPicker}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="picker-overlay" onclick={() => showGalleryPicker = false}>
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div class="picker-modal" onclick={(e) => e.stopPropagation()}>
      <h3>Select an image from gallery</h3>
      {#if galleryImages.length === 0}
        <p class="picker-empty">No images in gallery yet.</p>
      {:else}
        <div class="picker-grid">
          {#each galleryImages as img (img.id)}
            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
            <div class="picker-item" onclick={() => pickImage(img)}>
              <img src={img.image_url} alt={img.prompt} />
            </div>
          {/each}
        </div>
      {/if}
      <button class="cancel-btn" onclick={() => showGalleryPicker = false}>Cancel</button>
    </div>
  </div>
{/if}

<div class="edit-page">
  <div class="top-bar">
    <h2>Edit Image</h2>
    <div class="top-actions">
      <button class="clear-btn" onclick={clearAll} disabled={processing}>
        <X size={14} /> Clear
      </button>
    </div>
  </div>

  <div class="layout side">
    <div class="form-panel">
      <!-- Source image -->
      <div class="source-section">
        <label>Source Image</label>
        {#if sourceUrl}
          <div class="source-preview">
            <img src={sourceUrl} alt="Source" />
            <button class="change-btn" onclick={() => { sourceId = null; sourceUrl = null; }} disabled={processing}>
              Change
            </button>
          </div>
        {:else}
          <div class="paste-area">
            <ClipboardPaste size={24} />
            <p>Paste an image (Ctrl+V)</p>
            <span class="paste-or">or</span>
            <button class="pick-btn" onclick={openGalleryPicker}>Pick from gallery</button>
          </div>
        {/if}
      </div>

      <!-- Filter selection -->
      <div class="controls">
        <div class="control-row">
          <div class="control-group">
            <label for="ie-filter">Filter</label>
            <select id="ie-filter" bind:value={filter} disabled={processing}>
              {#each IMAGE_FILTERS as f}
                <option value={f.id}>{f.label}</option>
              {/each}
            </select>
          </div>
        </div>

        {#if filter === 'aspect_crop'}
          <div class="control-group" style="margin-bottom: 12px;">
            <label for="ie-aspect">Aspect Ratio</label>
            <select id="ie-aspect" bind:value={aspectRatio} disabled={processing}>
              {#each ASPECT_RATIOS as ar}
                <option value={ar}>{ar}</option>
              {/each}
            </select>
          </div>
          {#if resultUrl}
            <button class="recrop-btn" onclick={handleRecrop} disabled={processing}>Re-crop</button>
          {:else}
            <p class="crop-hint">Click to set center, drag to set size</p>
          {/if}
        {:else if filter === 'stitch_2x'}
          <div class="checkbox-row">
            <label class="checkbox-label">
              <input type="checkbox" bind:checked={mirrorX} disabled={processing} />
              Mirror X
            </label>
            <label class="checkbox-label">
              <input type="checkbox" bind:checked={mirrorY} disabled={processing} />
              Mirror Y
            </label>
          </div>
        {:else if filter === 'integer_crop'}
          <div class="control-group" style="margin-bottom: 12px;">
            <label for="ie-divisor">Divisor</label>
            <input id="ie-divisor" type="number" min="2" max="16"
                   bind:value={divisor} disabled={processing} class="divisor-input" />
          </div>
          <div class="control-group">
            <label>Position</label>
            <div class="position-grid">
              {#each POSITIONS as row}
                {#each row as pos}
                  <button class="pos-btn" class:active={position === pos}
                          disabled={processing}
                          onclick={() => position = pos}>
                    {pos}
                  </button>
                {/each}
              {/each}
            </div>
          </div>
        {/if}

        {#if isSlow}
          <div class="actions">
            <button class="run-btn" onclick={handleRun} disabled={processing || !sourceId}>
              {processing ? 'Processing...' : 'Run'}
            </button>
          </div>
        {/if}

      </div>
    </div>

    <div class="preview-panel">
      {#if showCropUI}
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div class="crop-container">
          <img bind:this={cropImg} src={sourceUrl} alt="Crop source"
               onload={handleCropImgLoad}
               draggable="false" />
          <canvas bind:this={cropCanvas}
                  onmousedown={handleCropMouseDown}
                  onmousemove={handleCropMouseMove}
                  onmouseup={handleCropMouseUp}
                  onmouseleave={handleCropMouseUp}></canvas>
        </div>
      {:else if processing}
        <div class="preview-placeholder">
          <div class="spinner"></div>
          <span>Processing...</span>
        </div>
      {:else if resultError}
        <div class="preview-placeholder error">
          <span>Error: {resultError}</span>
        </div>
      {:else if resultUrl}
        <div class="preview-image">
          <img src={resultUrl} alt="Result" />
        </div>
        <div class="preview-actions">
          <button class="apply-btn" onclick={handleApplyToEditor} disabled={processing}>
            Apply
          </button>
          <button class="save-btn" onclick={handleSave} disabled={saving}>
            <Save size={14} /> {saving ? 'Saving...' : 'Save to Gallery'}
          </button>
        </div>
      {/if}
    </div>
  </div>
</div>

<style>
  .edit-page {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 28px;
  }

  .top-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 20px;
  }

  .top-bar h2 {
    font-size: 18px;
    font-weight: 600;
    margin: 0;
  }

  .top-actions {
    display: flex;
    gap: 6px;
    align-items: center;
  }

  .clear-btn {
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border);
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 13px;
    padding: 6px 12px;
  }

  .clear-btn:hover:not(:disabled) {
    color: var(--text);
    border-color: var(--text-muted);
  }

  .layout {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .layout.side {
    flex-direction: row;
    align-items: flex-start;
  }

  .layout.side .form-panel {
    width: 340px;
    flex-shrink: 0;
  }

  .layout.side .preview-panel {
    flex: 1;
    min-width: 0;
  }

  /* Source section */
  .source-section {
    margin-bottom: 16px;
  }

  .source-section > label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: var(--text-dim);
    margin-bottom: 8px;
  }

  .paste-area {
    border: 2px dashed var(--border);
    border-radius: var(--radius);
    padding: 32px 20px;
    text-align: center;
    color: var(--text-muted);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
  }

  .paste-area p {
    font-size: 14px;
    margin: 0;
  }

  .paste-or {
    font-size: 12px;
    color: var(--text-muted);
  }

  .pick-btn {
    background: transparent;
    color: var(--accent);
    border: 1px solid var(--accent);
    font-size: 13px;
    padding: 6px 16px;
    cursor: pointer;
  }

  .pick-btn:hover {
    background: var(--accent);
    color: white;
  }

  .source-preview {
    position: relative;
    display: inline-block;
    border-radius: var(--radius);
    overflow: hidden;
    border: 1px solid var(--border);
  }

  .source-preview img {
    max-width: 300px;
    max-height: 200px;
    display: block;
    object-fit: contain;
  }

  .change-btn {
    position: absolute;
    top: 6px;
    right: 6px;
    background: rgba(0, 0, 0, 0.6);
    color: white;
    border: none;
    font-size: 12px;
    padding: 4px 10px;
    border-radius: 4px;
    cursor: pointer;
  }

  .change-btn:hover { background: rgba(0, 0, 0, 0.8); }

  /* Controls */
  .control-row {
    display: flex;
    gap: 16px;
    margin-bottom: 16px;
  }

  .control-group {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .control-group label {
    font-size: 13px;
    font-weight: 500;
    color: var(--text-dim);
  }

  .control-group select {
    font-family: inherit;
    font-size: 14px;
    color: var(--text);
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 8px 12px;
  }

  .checkbox-row {
    display: flex;
    gap: 16px;
    margin-bottom: 12px;
  }

  .checkbox-label {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: var(--text-dim);
    cursor: pointer;
  }

  .checkbox-label input[type="checkbox"] {
    cursor: pointer;
  }

  .divisor-input {
    width: 80px;
    font-size: 14px;
    font-family: monospace;
    padding: 8px 12px;
  }

  .position-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 4px;
    width: 160px;
    margin-top: 4px;
  }

  .pos-btn {
    padding: 6px 0;
    font-size: 12px;
    font-weight: 600;
    background: var(--bg-input);
    color: var(--text-muted);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    cursor: pointer;
    text-align: center;
  }

  .pos-btn:hover:not(:disabled) {
    color: var(--text);
    border-color: var(--text-muted);
  }

  .pos-btn.active {
    background: var(--accent);
    color: white;
    border-color: var(--accent);
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    margin-top: 12px;
  }

  .run-btn {
    background: var(--accent);
    color: white;
    font-weight: 500;
    padding: 10px 28px;
    font-size: 15px;
  }

  .run-btn:hover:not(:disabled) {
    background: var(--accent-hover);
  }

  /* Preview */
  .preview-placeholder {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-height: 200px;
    color: var(--text-muted);
    font-size: 13px;
    background: var(--bg-input);
    border-radius: var(--radius);
  }

  .preview-placeholder.error { color: var(--error); }

  .spinner {
    width: 24px;
    height: 24px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  .preview-image {
    border-radius: var(--radius);
    overflow: hidden;
    display: flex;
    justify-content: center;
    background: var(--bg-input);
  }

  .preview-image img {
    max-width: 100%;
    max-height: 600px;
    object-fit: contain;
    display: block;
  }

  .preview-actions {
    display: flex;
    gap: 8px;
    margin-top: 12px;
    justify-content: flex-end;
  }

  .apply-btn {
    background: var(--accent);
    color: white;
    font-weight: 500;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    padding: 8px 16px;
  }

  .apply-btn:hover:not(:disabled) {
    background: var(--accent-hover);
  }

  .save-btn {
    background: var(--success);
    color: white;
    font-weight: 500;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    padding: 8px 16px;
  }

  .save-btn:hover:not(:disabled) {
    filter: brightness(1.1);
  }

  /* Gallery picker overlay */
  .picker-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.7);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 2000;
  }

  .picker-modal {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 24px;
    max-width: 700px;
    max-height: 80vh;
    overflow-y: auto;
    width: 90%;
  }

  .picker-modal h3 {
    font-size: 16px;
    margin-bottom: 16px;
  }

  .picker-empty {
    color: var(--text-muted);
    text-align: center;
    padding: 24px;
  }

  .picker-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 10px;
    margin-bottom: 16px;
  }

  .picker-item {
    cursor: pointer;
    border: 2px solid transparent;
    border-radius: var(--radius);
    overflow: hidden;
    transition: border-color 0.15s;
  }

  .picker-item:hover {
    border-color: var(--accent);
  }

  .picker-item img {
    width: 100%;
    aspect-ratio: 1;
    object-fit: cover;
    display: block;
  }

  .cancel-btn {
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border);
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 13px;
    padding: 6px 14px;
  }

  .cancel-btn:hover {
    color: var(--text);
    border-color: var(--text-muted);
  }

  /* Aspect Crop interactive UI */
  .crop-container {
    position: relative;
    display: inline-block;
    border-radius: var(--radius);
    overflow: hidden;
    background: var(--bg-input);
  }

  .crop-container img {
    display: block;
    max-width: 100%;
    max-height: 600px;
    user-select: none;
    pointer-events: none;
  }

  .crop-container canvas {
    position: absolute;
    top: 0;
    left: 0;
    cursor: crosshair;
  }

  .crop-hint {
    font-size: 12px;
    color: var(--text-muted);
    margin: 4px 0 0;
  }

  .recrop-btn {
    background: transparent;
    color: var(--accent);
    border: 1px solid var(--accent);
    font-size: 13px;
    padding: 6px 16px;
    cursor: pointer;
    margin-top: 4px;
  }

  .recrop-btn:hover:not(:disabled) {
    background: var(--accent);
    color: white;
  }
</style>
