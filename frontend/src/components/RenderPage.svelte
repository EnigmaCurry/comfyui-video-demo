<script>
  import { Film, Download, RefreshCw } from 'lucide-svelte';
  import { renderFinal, getFinalStatus } from '../lib/api.js';

  let { projectId = '', projectName = '', onstatus } = $props();

  let rendering = $state(false);
  let videoUrl = $state(null);
  let filename = $state(null);
  let renderVersion = $state(0);

  // Check if final already exists on mount
  async function init() {
    try {
      const data = await getFinalStatus();
      if (data.url) {
        videoUrl = data.url;
        filename = data.filename;
        renderVersion = Date.now();
      }
    } catch {}
  }

  async function handleRender() {
    rendering = true;
    onstatus({ detail: 'Assembling final film...' });
    try {
      const data = await renderFinal();
      videoUrl = data.url;
      filename = data.filename;
      renderVersion = Date.now();
      onstatus({ detail: 'Final film assembled!' });
    } catch (e) {
      onstatus({ detail: `Assembly failed: ${e.message}` });
    } finally {
      rendering = false;
    }
  }

  function downloadUrl() {
    if (!videoUrl) return null;
    return `${videoUrl}?v=${renderVersion}`;
  }

  init();
</script>

<div class="render-page">
  <div class="hero">
    <Film size={48} />
    <h2>{projectName || 'Untitled Film'}</h2>
    <p class="hint">Assemble all scored sections into one final video.</p>
  </div>

  <div class="actions">
    <button class="render-btn" onclick={handleRender} disabled={rendering}>
      {#if rendering}
        <div class="spinner"></div> Assembling...
      {:else if videoUrl}
        <RefreshCw size={18} /> Re-assemble
      {:else}
        <Film size={18} /> Assemble Final Film
      {/if}
    </button>
  </div>

  {#if videoUrl}
    <div class="preview">
      <!-- svelte-ignore a11y_media_has_caption -->
      <video src="{videoUrl}?v={renderVersion}" controls></video>
    </div>

    <div class="download-bar">
      <a class="download-btn" href="{videoUrl}?v={renderVersion}" download={filename}>
        <Download size={18} /> Download {filename}
      </a>
    </div>
  {/if}
</div>

<style>
  .render-page {
    max-width: 900px;
    margin: 0 auto;
  }

  .hero {
    text-align: center;
    padding: 40px 20px 30px;
    color: var(--text-dim);
  }

  .hero h2 {
    font-size: 24px;
    font-weight: 600;
    color: var(--text);
    margin: 16px 0 8px;
  }

  .hint {
    font-size: 14px;
    color: var(--text-muted);
  }

  .actions {
    display: flex;
    justify-content: center;
    margin-bottom: 24px;
  }

  .render-btn {
    background: var(--accent);
    color: white;
    font-weight: 600;
    font-size: 16px;
    padding: 14px 36px;
    display: inline-flex;
    align-items: center;
    gap: 10px;
  }

  .render-btn:hover:not(:disabled) { background: var(--accent-hover); }

  .spinner {
    width: 18px; height: 18px;
    border: 3px solid rgba(255,255,255,0.3);
    border-top-color: white;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  .preview {
    background: #000;
    border-radius: var(--radius-lg);
    overflow: hidden;
    margin-bottom: 20px;
  }

  .preview video {
    width: 100%;
    display: block;
  }

  .download-bar {
    display: flex;
    justify-content: center;
    margin-bottom: 40px;
  }

  .download-btn {
    background: var(--success);
    color: white;
    font-weight: 500;
    font-size: 15px;
    padding: 12px 32px;
    border-radius: var(--radius);
    display: inline-flex;
    align-items: center;
    gap: 8px;
    text-decoration: none;
    transition: filter 0.15s;
  }

  .download-btn:hover { filter: brightness(1.1); }
</style>
