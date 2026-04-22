<script>
  import { Sparkles, RefreshCw, Save, X, RotateCcw, Undo2, Columns2 } from 'lucide-svelte';
  import { galleryGenerate, galleryPreviewStatus, galleryCancel, galleryRefine, galleryUndo, gallerySave, galleryEdit, galleryList, T2I_MODELS, RESOLUTIONS } from '../lib/api.js';

  let { project = $bindable(null), onstatus, ongallery, recreateImage = $bindable(null) } = $props();

  // Form state
  let prompt = $state('');
  let negPrompt = $state('');
  let model = $state('hidream');
  let resWidth = $state(1024);
  let resHeight = $state(576);
  let seedInput = $state('');
  let generating = $state(false);
  let saving = $state(false);
  let cancelled = $state(false);

  // Preview state
  let previewUrl = $state(null);
  let previewStatus = $state(null);
  let previewError = $state('');
  let previewSeed = $state(null);

  // History: [{prompt, model, seed, previewUrl}]
  let history = $state([]);

  // Two-image model state
  let isTwoImageModel = $derived(T2I_MODELS.find(m => m.id === model)?.twoImage ?? false);
  let galleryImages = $state([]);
  let figure1Id = $state('');
  let figure2Id = $state('');

  async function fetchGalleryImages() {
    try {
      const data = await galleryList();
      galleryImages = data.images.filter(i => i.image_url);
    } catch { galleryImages = []; }
  }

  $effect(() => {
    if (isTwoImageModel) fetchGalleryImages();
  });

  // Refinement
  let refinePrompt = $state('');

  let hasPreview = $derived(previewStatus === 'done' && previewUrl);
  let canUndo = $derived(history.length > 1 && !generating);

  function clearAll() {
    prompt = '';
    negPrompt = '';
    refinePrompt = '';
    history = [];
    previewUrl = null;
    previewStatus = null;
    previewError = '';
    previewSeed = null;
    generating = false;
    saving = false;
    seedInput = '';
    comparing = false;
    figure1Id = '';
    figure2Id = '';
  }

  async function handleGenerate() {
    if (!prompt.trim()) return;
    generating = true;
    cancelled = false;
    previewUrl = null;
    previewStatus = 'rendering';
    previewError = '';
    history = [];
    try {
      const opts = {
        prompt: prompt.trim(),
        negative_prompt: negPrompt.trim(),
        model,
        width: resWidth,
        height: resHeight,
      };
      if (seedInput.trim()) {
        opts.seed = parseInt(seedInput.trim(), 10);
      }
      if (isTwoImageModel) {
        opts.figure1_id = figure1Id;
        opts.figure2_id = figure2Id;
      }
      const modelLabel = T2I_MODELS.find(m => m.id === model)?.label || model;
      // Show the prompt immediately in history while generating
      history = [{ prompt: opts.prompt, model: modelLabel, seed: null, previewUrl: null }];
      prompt = '';
      const data = await galleryGenerate(opts);
      project = data.project;
      await pollPreview();
      if (previewStatus === 'done') {
        history = [{ prompt: opts.prompt, model: modelLabel, seed: previewSeed, previewUrl }];
      }
    } catch (e) {
      if (!cancelled) {
        previewStatus = 'error';
        previewError = e.message;
        onstatus?.({ detail: `Failed: ${e.message}` });
      }
    } finally {
      generating = false;
    }
  }

  async function handleNewSeed() {
    if (!history.length) return;
    const current = history[history.length - 1];
    const isRefinement = history.length > 1;
    const first = history[0];
    const isT2I = T2I_MODELS.some(m => m.label === first.model);

    if (isRefinement || !isT2I) {
      // Re-run the latest refinement step with a new seed (undo then redo)
      generating = true;
      cancelled = false;
      previewStatus = 'rendering';
      previewError = '';
      const redoPrompt = current.prompt;
      const prevHistory = isRefinement ? history.slice(0, -1) : history;
      history = [...prevHistory, { prompt: redoPrompt, model: 'Capybara I2I', seed: null, previewUrl: null }];
      try {
        if (isRefinement) {
          await galleryUndo();
        }
        await galleryRefine({
          prompt: redoPrompt,
          negative_prompt: negPrompt.trim(),
        });
        await pollPreview();
        if (previewStatus === 'done') {
          history = [...prevHistory, {
            prompt: redoPrompt,
            model: 'Capybara I2I',
            seed: previewSeed,
            previewUrl,
          }];
        }
      } catch (e) {
        if (!cancelled) {
          previewStatus = 'error';
          previewError = e.message;
        }
      } finally {
        generating = false;
      }
    } else {
      // Original T2I generation — regenerate from scratch with new seed
      generating = true;
      cancelled = false;
      previewUrl = null;
      previewStatus = 'rendering';
      previewError = '';
      history = [{ prompt: first.prompt, model: first.model, seed: null, previewUrl: null }];
      try {
        const modelId = T2I_MODELS.find(m => m.label === first.model)?.id || 'hidream';
        const modelDef = T2I_MODELS.find(m => m.label === first.model);
        const opts = {
          prompt: first.prompt,
          negative_prompt: negPrompt.trim(),
          model: modelId,
          width: resWidth,
          height: resHeight,
        };
        if (modelDef?.twoImage && figure1Id && figure2Id) {
          opts.figure1_id = figure1Id;
          opts.figure2_id = figure2Id;
        }
        const data = await galleryGenerate(opts);
        project = data.project;
        await pollPreview();
        if (previewStatus === 'done') {
          history = [{
            prompt: first.prompt,
            model: first.model,
            seed: previewSeed,
            previewUrl,
          }];
        }
      } catch (e) {
        if (!cancelled) {
          previewStatus = 'error';
          previewError = e.message;
        }
      } finally {
        generating = false;
      }
    }
  }

  async function handleRefine() {
    if (!refinePrompt.trim()) return;
    generating = true;
    cancelled = false;
    previewStatus = 'rendering';
    previewError = '';
    const refinedPrompt = refinePrompt.trim();
    refinePrompt = '';
    try {
      await galleryRefine({
        prompt: refinedPrompt,
        negative_prompt: negPrompt.trim(),
      });
      await pollPreview();
      if (previewStatus === 'done') {
        history = [...history, {
          prompt: refinedPrompt,
          model: 'Capybara I2I',
          seed: previewSeed,
          previewUrl,
        }];
      }
    } catch (e) {
      if (!cancelled) {
        previewStatus = 'error';
        previewError = e.message;
        onstatus?.({ detail: `Refine failed: ${e.message}` });
      }
    } finally {
      generating = false;
    }
  }

  async function handleUndo() {
    if (!canUndo) return;
    try {
      const data = await galleryUndo();
      history = history.slice(0, -1);
      const prev = history[history.length - 1];
      previewUrl = data.image_url + '?t=' + Date.now();
      previewSeed = data.seed;
      previewStatus = 'done';
      previewError = '';
      onstatus?.({ detail: 'Undone.' });
    } catch (e) {
      onstatus?.({ detail: `Undo failed: ${e.message}` });
    }
  }

  async function handleCancel() {
    cancelled = true;
    try {
      const data = await galleryCancel();
      if (data.current?.image_url) {
        previewUrl = data.current.image_url + '?t=' + Date.now();
        previewSeed = data.current.seed;
        previewStatus = 'done';
      } else if (history.length) {
        const prev = history[history.length - 1];
        previewUrl = prev.previewUrl;
        previewSeed = prev.seed;
        previewStatus = 'done';
      } else {
        previewStatus = null;
        previewUrl = null;
      }
    } catch {
      previewStatus = null;
      previewUrl = null;
    }
    generating = false;
    previewError = '';
    onstatus?.({ detail: 'Generation cancelled.' });
  }

  async function pollPreview() {
    while (!cancelled) {
      try {
        const data = await galleryPreviewStatus();
        previewStatus = data.status;
        previewSeed = data.seed;
        if (data.image_url) previewUrl = data.image_url + '?t=' + Date.now();
        if (data.error_message) previewError = data.error_message;
        if (data.status === 'done' || data.status === 'error') break;
      } catch {
        break;
      }
      await new Promise(r => setTimeout(r, 2000));
    }
  }

  async function handleSave() {
    saving = true;
    try {
      const data = await gallerySave();
      project = data.project;
      onstatus?.({ detail: 'Image saved to gallery.' });
      clearAll();
    } catch (e) {
      onstatus?.({ detail: `Save failed: ${e.message}` });
    } finally {
      saving = false;
    }
  }

  function handleWindowKeydown(e) {
    if (e.key === ' ' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) {
      e.preventDefault();
      if (hasPreview && !generating) handleNewSeed();
    }
  }

  function handleKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (hasPreview) {
        handleRefine();
      } else {
        handleGenerate();
      }
    }
  }

  function editSummary() {
    if (!history.length) return;
    prompt = history[0].prompt;
    history = [];
    refinePrompt = '';
    previewUrl = null;
    previewStatus = null;
    previewSeed = null;
    comparing = false;
  }

  async function editRefinement(index) {
    if (index <= 0 || index >= history.length || generating) return;
    const editPrompt = history[index].prompt;
    const undoCount = history.length - index;
    try {
      for (let u = 0; u < undoCount; u++) {
        const data = await galleryUndo();
        if (u === undoCount - 1) {
          previewUrl = data.image_url + '?t=' + Date.now();
          previewSeed = data.seed;
          previewStatus = 'done';
        }
      }
      history = history.slice(0, index);
      refinePrompt = editPrompt;
      comparing = false;
    } catch (e) {
      onstatus?.({ detail: `Revert failed: ${e.message}` });
    }
  }

  // Handle recreate from gallery — load image into refinement mode
  $effect(() => {
    if (recreateImage) {
      const img = recreateImage;
      recreateImage = null;
      clearAll();
      (async () => {
        try {
          const data = await galleryEdit(img.id);
          project = data.project;
          negPrompt = data.negative_prompt || '';
          resWidth = data.width || 1024;
          resHeight = data.height || 576;
          previewUrl = data.image_url + '?t=' + Date.now();
          previewSeed = data.seed;
          previewStatus = 'done';
          const modelLabel = T2I_MODELS.find(m => m.id === data.model)?.label || data.model;
          history = [{ prompt: data.prompt, model: modelLabel, seed: data.seed, previewUrl }];
        } catch (e) {
          onstatus?.({ detail: `Failed to load image for editing: ${e.message}` });
        }
      })();
    }
  });

  let sidePreview = true;
  let fullscreen = $state(false);

  // Comparison slider state
  let comparing = $state(false);
  let sliderPos = $state(50);
  let sliderDragging = $state(false);
  let sliderContainer = $state(null);

  let beforeUrl = $derived(history.length > 1 ? history[history.length - 2].previewUrl : null);
  let canCompare = $derived(hasPreview && beforeUrl != null);

  function handleSliderMove(e) {
    if (!sliderDragging || !sliderContainer) return;
    const rect = sliderContainer.getBoundingClientRect();
    const x = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
    sliderPos = Math.max(0, Math.min(100, (x / rect.width) * 100));
  }

  function stopSliderDrag() {
    sliderDragging = false;
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<svelte:window onmousemove={handleSliderMove} onmouseup={stopSliderDrag}
               ontouchmove={handleSliderMove} ontouchend={stopSliderDrag}
               onkeydown={handleWindowKeydown} />

{#if fullscreen && previewUrl}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="fullscreen-overlay" onclick={() => fullscreen = false}>
    <img src={previewUrl} alt="Full size preview" />
  </div>
{/if}

<div class="create-page">
  <div class="top-bar">
    <h2>Generate an Image</h2>
    <div class="top-actions">
      <button class="clear-btn" onclick={clearAll} disabled={generating}>
        <RotateCcw size={14} /> Clear
      </button>
    </div>
  </div>

  <div class="layout side">
    <div class="form-panel">
      {#if !history.length}
        <!-- Initial generation form -->
        <div class="controls">
          <div class="control-row">
            <div class="control-group">
              <label for="ig-model">Model</label>
              <select id="ig-model" bind:value={model} disabled={generating}>
                {#each T2I_MODELS as m}
                  <option value={m.id}>{m.label}</option>
                {/each}
              </select>
            </div>
            {#if !isTwoImageModel}
            <div class="control-group">
              <label for="ig-resolution">Resolution</label>
              <select id="ig-resolution" disabled={generating}
                      onchange={(e) => {
                        const r = RESOLUTIONS[e.target.selectedIndex];
                        resWidth = r.w; resHeight = r.h;
                      }}>
                {#each RESOLUTIONS as r}
                  <option selected={r.w === resWidth && r.h === resHeight}>{r.label}</option>
                {/each}
              </select>
            </div>
            {/if}
            <div class="control-group">
              <label for="ig-seed">Seed <span class="optional">(blank = random)</span></label>
              <input id="ig-seed" type="text" inputmode="numeric"
                     placeholder="random"
                     bind:value={seedInput}
                     disabled={generating}
                     class="seed-input" />
            </div>
          </div>

          <div class="prompt-section">
            <label for="ig-prompt">Prompt</label>
            <textarea id="ig-prompt"
              placeholder="A vast desert landscape at golden hour, ancient ruins half-buried in sand, dramatic clouds..."
              bind:value={prompt}
              disabled={generating}
              onkeydown={handleKeydown}
              rows="3"
            ></textarea>
          </div>

          {#if !isTwoImageModel}
          <div class="prompt-section">
            <label for="ig-neg">Negative prompt <span class="optional">(optional)</span></label>
            <textarea id="ig-neg"
              placeholder="blurry, low quality, text, watermark..."
              bind:value={negPrompt}
              disabled={generating}
              rows="2"
            ></textarea>
          </div>
          {/if}

          {#if isTwoImageModel}
          <div class="figure-pickers">
            <div class="figure-picker">
              <label>Figure 1</label>
              {#if galleryImages.length === 0}
                <p class="figure-empty">No gallery images. Save some images first.</p>
              {:else}
                <select bind:value={figure1Id} disabled={generating}>
                  <option value="">-- Select image --</option>
                  {#each galleryImages as gi}
                    <option value={gi.id}>{gi.prompt ? gi.prompt.slice(0, 60) : gi.id} ({gi.width}x{gi.height})</option>
                  {/each}
                </select>
                {#if figure1Id}
                  {@const fig1 = galleryImages.find(i => i.id === figure1Id)}
                  {#if fig1}
                    <img class="figure-thumb" src={fig1.image_url} alt="Figure 1" />
                  {/if}
                {/if}
              {/if}
            </div>
            <div class="figure-picker">
              <label>Figure 2</label>
              {#if galleryImages.length === 0}
                <p class="figure-empty">No gallery images. Save some images first.</p>
              {:else}
                <select bind:value={figure2Id} disabled={generating}>
                  <option value="">-- Select image --</option>
                  {#each galleryImages as gi}
                    <option value={gi.id}>{gi.prompt ? gi.prompt.slice(0, 60) : gi.id} ({gi.width}x{gi.height})</option>
                  {/each}
                </select>
                {#if figure2Id}
                  {@const fig2 = galleryImages.find(i => i.id === figure2Id)}
                  {#if fig2}
                    <img class="figure-thumb" src={fig2.image_url} alt="Figure 2" />
                  {/if}
                {/if}
              {/if}
            </div>
          </div>
          {/if}

          <div class="actions">
            <button class="generate-btn" onclick={handleGenerate}
                    disabled={generating || !prompt.trim() || (isTwoImageModel && (!figure1Id || !figure2Id))}>
              <Sparkles size={16} />
              {generating ? 'Generating...' : 'Generate'}
            </button>
          </div>
        </div>
      {:else}
        <!-- History + refinement mode -->
        <div class="history-list">
          {#each history as entry, i}
            <div class="history-entry" class:first={i === 0} class:current={i === history.length - 1}>
              <div class="history-header">
                <span class="history-step">{i === 0 ? 'Original' : `Refine ${i}`}</span>
                <span class="history-model">{entry.model}</span>
              </div>
              <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
              <p class="history-prompt clickable"
                 onclick={() => i === 0 ? editSummary() : editRefinement(i)}
                 title="Click to edit">{entry.prompt}</p>
            </div>
          {/each}
        </div>

        {#if hasPreview}
          <div class="preview-actions">
            <button class="action-btn" onclick={handleUndo} disabled={!canUndo} title="Undo last refinement">
              <Undo2 size={14} /> Undo
            </button>
            <button class="action-btn" onclick={handleNewSeed} disabled={generating}>
              <RefreshCw size={14} /> New Seed
            </button>
            {#if canCompare}
              <button class="action-btn" class:active={comparing}
                      onclick={() => { comparing = !comparing; sliderPos = 50; }}>
                <Columns2 size={14} /> Compare
              </button>
            {/if}
            <button class="save-btn" onclick={handleSave} disabled={saving}>
              <Save size={14} /> {saving ? 'Saving...' : 'Save'}
            </button>
          </div>

          <div class="refine-section">
            <label for="ig-refine">Refine</label>
            <textarea id="ig-refine"
              placeholder="Change the background to a snowy mountain, make the sky more dramatic..."
              bind:value={refinePrompt}
              disabled={generating}
              onkeydown={handleKeydown}
              rows="2"
            ></textarea>
            <div class="actions">
              <button class="generate-btn" onclick={handleRefine}
                      disabled={generating || !refinePrompt.trim()}>
                <Sparkles size={16} /> Refine
              </button>
            </div>
          </div>
        {/if}
      {/if}
    </div>

    {#if previewStatus}
      <div class="preview-panel">
        {#if previewStatus === 'rendering'}
          <div class="preview-placeholder">
            <div class="spinner"></div>
            <span>Generating...</span>
            <button class="cancel-btn" onclick={handleCancel}>
              <X size={14} /> Cancel
            </button>
          </div>
        {:else if previewStatus === 'error'}
          <div class="preview-placeholder error">
            <span>Error: {previewError}</span>
          </div>
        {:else if previewUrl}
          {#if comparing && beforeUrl}
            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
            <div class="compare-container" bind:this={sliderContainer}
                 onmousedown={() => sliderDragging = true}
                 ontouchstart={() => sliderDragging = true}>
              <div class="compare-layer compare-before">
                <img src={beforeUrl} alt="Before" />
              </div>
              <div class="compare-layer compare-after" style="clip-path: inset(0 0 0 {sliderPos}%)">
                <img src={previewUrl} alt="After" />
              </div>
              <div class="compare-handle" style="left: {sliderPos}%">
                <div class="compare-line"></div>
                <div class="compare-knob">
                  <span class="compare-arrow">&lsaquo;</span>
                  <span class="compare-arrow">&rsaquo;</span>
                </div>
              </div>
              <div class="compare-label compare-label-left">Before</div>
              <div class="compare-label compare-label-right">After</div>
            </div>
          {:else}
            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
            <div class="preview-image" onclick={() => fullscreen = true}>
              <img src={previewUrl} alt="Preview" />
            </div>
          {/if}
        {/if}
      </div>
    {/if}
  </div>
</div>

<style>
  .create-page {
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

  /* Layout */
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

  .layout.side .control-row {
    flex-direction: column;
  }

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

  .seed-input {
    width: 140px;
    font-size: 14px;
    font-family: monospace;
    padding: 8px 12px;
  }

  .prompt-section {
    margin-bottom: 12px;
  }

  .prompt-section label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: var(--text-dim);
    margin-bottom: 4px;
  }

  .optional {
    font-weight: 400;
    color: var(--text-muted);
  }

  .prompt-section textarea {
    width: 100%;
    resize: vertical;
    line-height: 1.6;
    font-size: 15px;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    margin-top: 4px;
  }

  .generate-btn {
    background: var(--accent);
    color: white;
    font-weight: 500;
    padding: 10px 28px;
    font-size: 15px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }

  .generate-btn:hover:not(:disabled) {
    background: var(--accent-hover);
  }

  /* History */
  .history-list {
    max-height: 240px;
    overflow-y: auto;
    margin-bottom: 12px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .history-entry {
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 8px 12px;
  }

  .history-entry.current {
    border-color: var(--accent);
  }

  .history-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 2px;
  }

  .history-step {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-muted);
  }

  .history-model {
    font-size: 11px;
    color: var(--accent);
    background: var(--accent-bg);
    padding: 1px 6px;
    border-radius: 3px;
  }

  .history-prompt {
    font-size: 13px;
    color: var(--text-dim);
    line-height: 1.4;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .history-prompt.clickable {
    cursor: pointer;
    transition: color 0.15s;
  }

  .history-prompt.clickable:hover {
    color: var(--text);
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

  .cancel-btn {
    margin-top: 8px;
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
    color: var(--error);
    border-color: var(--error);
  }

  .preview-image {
    cursor: pointer;
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
    flex-wrap: wrap;
  }

  .action-btn {
    background: var(--bg-card-hover);
    color: var(--text-dim);
    border: 1px solid var(--border);
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    padding: 8px 16px;
  }

  .action-btn:hover:not(:disabled) {
    color: var(--text);
    border-color: var(--text-muted);
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

  /* Refinement */
  .refine-section {
    margin-top: 16px;
    border-top: 1px solid var(--border);
    padding-top: 12px;
  }

  .refine-section label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: var(--text-dim);
    margin-bottom: 4px;
  }

  .refine-section textarea {
    width: 100%;
    resize: vertical;
    line-height: 1.6;
    font-size: 15px;
    margin-bottom: 4px;
  }

  /* Comparison slider */
  .compare-container {
    position: relative;
    border-radius: var(--radius);
    overflow: hidden;
    background: var(--bg-input);
    cursor: col-resize;
    user-select: none;
    -webkit-user-select: none;
  }

  .compare-layer {
    display: flex;
    justify-content: center;
  }

  .compare-layer img {
    max-width: 100%;
    max-height: 600px;
    object-fit: contain;
    display: block;
  }

  .compare-after {
    position: absolute;
    inset: 0;
    display: flex;
    justify-content: center;
  }

  .compare-after img {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }

  .compare-handle {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 0;
    transform: translateX(-50%);
    z-index: 10;
    pointer-events: none;
  }

  .compare-line {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 50%;
    width: 2px;
    background: white;
    transform: translateX(-50%);
    box-shadow: 0 0 4px rgba(0, 0, 0, 0.5);
  }

  .compare-knob {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: white;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 2px;
  }

  .compare-arrow {
    font-size: 16px;
    line-height: 1;
    color: #333;
    font-weight: 700;
  }

  .compare-label {
    position: absolute;
    top: 10px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: white;
    background: rgba(0, 0, 0, 0.5);
    padding: 3px 8px;
    border-radius: 4px;
    pointer-events: none;
    z-index: 5;
  }

  .compare-label-left { left: 10px; }
  .compare-label-right { right: 10px; }

  .action-btn.active {
    color: var(--accent);
    border-color: var(--accent);
  }

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

  /* Figure pickers for two-image models */
  .figure-pickers {
    display: flex;
    gap: 12px;
    margin-bottom: 12px;
  }

  .figure-picker {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .figure-picker label {
    font-size: 13px;
    font-weight: 500;
    color: var(--text-dim);
  }

  .figure-picker select {
    font-family: inherit;
    font-size: 13px;
    color: var(--text);
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 6px 8px;
    width: 100%;
  }

  .figure-thumb {
    max-width: 100%;
    max-height: 100px;
    object-fit: contain;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    margin-top: 4px;
  }

  .figure-empty {
    font-size: 12px;
    color: var(--text-muted);
  }
</style>
