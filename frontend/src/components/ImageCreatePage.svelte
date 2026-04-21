<script>
  import { Sparkles, RefreshCw, Save, X, RotateCcw } from 'lucide-svelte';
  import { galleryGenerate, galleryPreviewStatus, galleryCancel, galleryRefine, gallerySave, T2I_MODELS, RESOLUTIONS } from '../lib/api.js';

  let { project = $bindable(null), onstatus, ongallery } = $props();

  // Form state
  let prompt = $state('');
  let negPrompt = $state('');
  let model = $state('hidream');
  let resWidth = $state(1024);
  let resHeight = $state(576);
  let generating = $state(false);
  let saving = $state(false);
  let cancelled = $state(false);

  // Preview state
  let previewUrl = $state(null);
  let previewStatus = $state(null); // null | 'rendering' | 'done' | 'error'
  let previewError = $state('');
  let previewSeed = $state(null);

  // Summary state — once an image is generated, show prompt as summary
  let summaryPrompt = $state('');
  let summaryModel = $state('');
  let summaryRes = $state('');

  // Refinement
  let refinePrompt = $state('');

  let hasPreview = $derived(previewStatus === 'done' && previewUrl);

  function clearAll() {
    prompt = '';
    negPrompt = '';
    refinePrompt = '';
    summaryPrompt = '';
    summaryModel = '';
    summaryRes = '';
    previewUrl = null;
    previewStatus = null;
    previewError = '';
    previewSeed = null;
    generating = false;
    saving = false;
  }

  async function handleGenerate() {
    if (!prompt.trim()) return;
    generating = true;
    cancelled = false;
    previewUrl = null;
    previewStatus = 'rendering';
    previewError = '';
    try {
      const opts = {
        prompt: prompt.trim(),
        negative_prompt: negPrompt.trim(),
        model,
        width: resWidth,
        height: resHeight,
      };
      const data = await galleryGenerate(opts);
      project = data.project;
      // Move prompt to summary
      summaryPrompt = prompt.trim();
      summaryModel = T2I_MODELS.find(m => m.id === model)?.label || model;
      summaryRes = `${resWidth}x${resHeight}`;
      prompt = '';
      await pollPreview();
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
    generating = true;
    cancelled = false;
    previewStatus = 'rendering';
    previewError = '';
    try {
      const opts = {
        prompt: summaryPrompt,
        negative_prompt: negPrompt.trim(),
        model: T2I_MODELS.find(m => m.label === summaryModel)?.id || 'hidream',
        width: resWidth,
        height: resHeight,
      };
      const data = await galleryGenerate(opts);
      project = data.project;
      await pollPreview();
    } catch (e) {
      if (!cancelled) {
        previewStatus = 'error';
        previewError = e.message;
      }
    } finally {
      generating = false;
    }
  }

  async function handleRefine() {
    if (!refinePrompt.trim()) return;
    generating = true;
    cancelled = false;
    previewStatus = 'rendering';
    previewError = '';
    try {
      await galleryRefine({
        prompt: refinePrompt.trim(),
        negative_prompt: negPrompt.trim(),
      });
      summaryPrompt = refinePrompt.trim();
      summaryModel = 'Capybara I2I';
      refinePrompt = '';
      await pollPreview();
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

  async function handleCancel() {
    cancelled = true;
    try {
      await galleryCancel();
    } catch {}
    generating = false;
    // If we had a previous preview, restore done state
    if (summaryPrompt && previewUrl) {
      previewStatus = 'done';
    } else {
      previewStatus = null;
      previewUrl = null;
    }
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
    prompt = summaryPrompt;
    summaryPrompt = '';
    summaryModel = '';
    summaryRes = '';
    refinePrompt = '';
    previewUrl = null;
    previewStatus = null;
    previewSeed = null;
  }

  let fullscreen = $state(false);
</script>

{#if fullscreen && previewUrl}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="fullscreen-overlay" onclick={() => fullscreen = false}>
    <img src={previewUrl} alt="Full size preview" />
  </div>
{/if}

<div class="create-page">
  <div class="top-bar">
    <h2>Generate an Image</h2>
    <button class="clear-btn" onclick={clearAll} disabled={generating}>
      <RotateCcw size={14} /> Clear
    </button>
  </div>

  {#if !summaryPrompt}
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

      <div class="prompt-section">
        <label for="ig-neg">Negative prompt <span class="optional">(optional)</span></label>
        <textarea id="ig-neg"
          placeholder="blurry, low quality, text, watermark..."
          bind:value={negPrompt}
          disabled={generating}
          rows="2"
        ></textarea>
      </div>

      <div class="actions">
        <button class="generate-btn" onclick={handleGenerate}
                disabled={generating || !prompt.trim()}>
          <Sparkles size={16} />
          {generating ? 'Generating...' : 'Generate'}
        </button>
      </div>
    </div>
  {:else}
    <!-- Summary + refinement mode -->
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div class="summary clickable" onclick={editSummary} title="Click to edit prompt">
      <div class="summary-meta">
        <span class="summary-badge">{summaryModel}</span>
        <span class="summary-badge">{summaryRes}</span>
        {#if previewSeed}<span class="summary-seed">seed: {previewSeed}</span>{/if}
      </div>
      <p class="summary-prompt">{summaryPrompt}</p>
    </div>
  {/if}

  {#if previewStatus}
    <div class="preview-section">
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
        <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
        <div class="preview-image" onclick={() => fullscreen = true}>
          <img src={previewUrl} alt="Preview" />
        </div>

        <div class="preview-actions">
          <button class="action-btn" onclick={handleNewSeed} disabled={generating}>
            <RefreshCw size={14} /> New Seed
          </button>
          <button class="save-btn" onclick={handleSave} disabled={saving}>
            <Save size={14} /> {saving ? 'Saving...' : 'Save to Gallery'}
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
    </div>
  {/if}
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

  /* Summary */
  .summary {
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px 16px;
    margin-bottom: 16px;
  }

  .summary.clickable {
    cursor: pointer;
    transition: border-color 0.15s;
  }

  .summary.clickable:hover {
    border-color: var(--text-muted);
  }

  .summary-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }

  .summary-badge {
    font-size: 11px;
    font-weight: 500;
    color: var(--accent);
    background: var(--accent-bg);
    padding: 2px 8px;
    border-radius: 4px;
  }

  .summary-seed {
    font-size: 11px;
    color: var(--text-muted);
    font-family: monospace;
  }

  .summary-prompt {
    font-size: 14px;
    color: var(--text);
    line-height: 1.5;
  }

  /* Preview */
  .preview-section {
    margin-top: 8px;
  }

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
    margin-top: 20px;
    border-top: 1px solid var(--border);
    padding-top: 16px;
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
