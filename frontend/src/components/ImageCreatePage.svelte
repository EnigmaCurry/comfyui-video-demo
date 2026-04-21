<script>
  import { Sparkles, RefreshCw, Save } from 'lucide-svelte';
  import { galleryGenerate, galleryPreviewStatus, gallerySave, T2I_MODELS, RESOLUTIONS } from '../lib/api.js';

  let { project = $bindable(null), onstatus, ongallery } = $props();

  let prompt = $state('');
  let negPrompt = $state('');
  let model = $state('hidream');
  let resWidth = $state(1024);
  let resHeight = $state(576);
  let generating = $state(false);
  let saving = $state(false);

  // Preview state
  let previewUrl = $state(null);
  let previewStatus = $state(null); // null | 'rendering' | 'done' | 'error'
  let previewError = $state('');
  let previewSeed = $state(null);

  async function handleGenerate(newSeed = true) {
    if (!prompt.trim()) return;
    generating = true;
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
      if (!newSeed && previewSeed != null) {
        opts.seed = previewSeed;
      }
      const data = await galleryGenerate(opts);
      project = data.project;
      await pollPreview();
    } catch (e) {
      previewStatus = 'error';
      previewError = e.message;
      onstatus?.({ detail: `Failed: ${e.message}` });
    } finally {
      generating = false;
    }
  }

  async function pollPreview() {
    while (true) {
      try {
        const data = await galleryPreviewStatus();
        previewStatus = data.status;
        previewSeed = data.seed;
        if (data.image_url) previewUrl = data.image_url;
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
      // Reset for next image
      previewUrl = null;
      previewStatus = null;
      previewSeed = null;
    } catch (e) {
      onstatus?.({ detail: `Save failed: ${e.message}` });
    } finally {
      saving = false;
    }
  }

  function handleKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleGenerate();
    }
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
      <button class="generate-btn" onclick={() => handleGenerate()}
              disabled={generating || !prompt.trim()}>
        <Sparkles size={16} />
        {generating ? 'Generating...' : 'Generate'}
      </button>
    </div>
  </div>

  {#if previewStatus}
    <div class="preview-section">
      <h3>Preview</h3>
      {#if previewStatus === 'rendering'}
        <div class="preview-placeholder">
          <div class="spinner"></div>
          <span>Generating...</span>
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
        <div class="preview-info">
          <span class="seed-label">seed: {previewSeed}</span>
        </div>
        <div class="preview-actions">
          <button class="action-btn" onclick={() => handleGenerate(true)}
                  disabled={generating}>
            <RefreshCw size={14} /> New Seed
          </button>
          <button class="save-btn" onclick={handleSave}
                  disabled={saving}>
            <Save size={14} /> {saving ? 'Saving...' : 'Save to Gallery'}
          </button>
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

  .preview-section {
    margin-top: 24px;
    border-top: 1px solid var(--border);
    padding-top: 20px;
  }

  .preview-section h3 {
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 12px;
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

  .preview-info {
    margin-top: 8px;
  }

  .seed-label {
    font-size: 12px;
    color: var(--text-muted);
    font-family: monospace;
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
