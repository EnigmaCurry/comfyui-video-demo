<script>
  import { Sparkles, RefreshCw, Play, RotateCcw, Scissors, Merge } from 'lucide-svelte';
  import { updateSection, suggestSoundtrackPrompt, renderSoundtrack,
           getSoundtrackStatus, splitSections, unsplitSections } from '../lib/api.js';

  let { sections = $bindable([]), transitions = [], projectId = '',
        onstatus, onreset } = $props();

  let polling = $state({});
  let renderVersion = $state({});
  let suggesting = $state({});

  // Poll any rendering sections on load
  $effect(() => {
    for (const sec of sections) {
      if (sec.status === 'rendering' && !polling[sec.id]) {
        pollStatus(sec);
      }
    }
  });

  function getTransition(id) {
    return transitions.find(t => t.id === id);
  }

  function previewUrl(sec) {
    if (!sec?.preview_filename || !projectId) return null;
    return `/api/projects/${projectId}/videos/${sec.preview_filename}?v=${renderVersion[sec.id] || 0}`;
  }

  async function handleSuggest(sec) {
    suggesting[sec.id] = true;
    onstatus({ detail: `Generating soundtrack prompt for section ${sec.position + 1}...` });
    try {
      const data = await suggestSoundtrackPrompt(sec.id);
      sec.prompt = data.prompt;
      onstatus({ detail: 'Soundtrack prompt generated.' });
    } catch (e) {
      onstatus({ detail: `Failed: ${e.message}` });
    } finally {
      suggesting[sec.id] = false;
    }
  }

  async function handleSave(sec) {
    try {
      await updateSection(sec.id, { prompt: sec.prompt, bpm: sec.bpm, keyscale: sec.keyscale });
      onstatus({ detail: `Section ${sec.position + 1} saved.` });
    } catch (e) {
      onstatus({ detail: `Save failed: ${e.message}` });
    }
  }

  async function handleRender(sec) {
    if (!sec.prompt.trim()) {
      onstatus({ detail: 'Enter a soundtrack prompt first.' });
      return;
    }
    // Save first
    await updateSection(sec.id, { prompt: sec.prompt, bpm: sec.bpm, keyscale: sec.keyscale });
    onstatus({ detail: `Rendering soundtrack for section ${sec.position + 1}...` });
    sec.status = 'rendering';
    try {
      await renderSoundtrack(sec.id);
      pollStatus(sec);
    } catch (e) {
      onstatus({ detail: `Render failed: ${e.message}` });
      sec.status = 'error';
    }
  }

  async function pollStatus(sec) {
    if (polling[sec.id]) return;
    polling[sec.id] = true;
    while (sec.status === 'rendering') {
      await new Promise(r => setTimeout(r, 3000));
      try {
        const status = await getSoundtrackStatus(sec.id);
        sec.status = status.status;
        sec.error_message = status.error_message;
        if (status.seed != null) sec.seed = status.seed;
        if (status.preview_url) {
          sec.preview_filename = status.preview_url.split('/').pop();
          renderVersion[sec.id] = Date.now();
        }
      } catch { break; }
    }
    polling[sec.id] = false;
  }

  function handleVideoPlay(e) {
    document.querySelectorAll('.section-card video').forEach(v => {
      if (v !== e.target) { v.pause(); v.currentTime = 0; }
    });
  }

  function handleVideoPause(e) { e.target.currentTime = 0; }

  async function handleSplitAt(sectionIndex, splitAfterTrIndex) {
    // Split a section into two at the given transition boundary
    const newGroups = sections.map(s => [...s.transition_ids]);
    const group = newGroups[sectionIndex];
    const left = group.slice(0, splitAfterTrIndex + 1);
    const right = group.slice(splitAfterTrIndex + 1);
    newGroups.splice(sectionIndex, 1, left, right);
    onstatus({ detail: 'Splitting section...' });
    try {
      const data = await splitSections(newGroups);
      if (onreset) onreset({ detail: { soundtrack_sections: data.sections } });
      onstatus({ detail: 'Section split.' });
    } catch (e) {
      onstatus({ detail: `Split failed: ${e.message}` });
    }
  }

  async function handleMergeAll() {
    onstatus({ detail: 'Merging all sections...' });
    try {
      const data = await unsplitSections();
      if (onreset) onreset({ detail: { soundtrack_sections: data.sections } });
      onstatus({ detail: 'All sections merged.' });
    } catch (e) {
      onstatus({ detail: `Merge failed: ${e.message}` });
    }
  }
</script>

{#if sections.length > 0}
  <div class="toolbar">
    {#if sections.length > 1}
      <button class="toolbar-btn" onclick={handleMergeAll}>
        <Merge size={14} /> Merge All
      </button>
    {/if}
  </div>

  <div class="sections">
    {#each sections as sec, si (sec.id)}
      <div class="section-card">
        <div class="card-header">
          <span class="position">{si + 1}</span>
          <span class="label">
            {sections.length === 1 ? 'Full Film' : `Section ${si + 1}`}
            — {sec.transition_ids.length} transition{sec.transition_ids.length !== 1 ? 's' : ''}
          </span>
          <span class="status-badge"
                class:pending={sec.status === 'pending'}
                class:rendering={sec.status === 'rendering'}
                class:done={sec.status === 'done'}
                class:error={sec.status === 'error'}>
            {sec.status}
          </span>
        </div>

        <!-- Transition thumbnails with split points -->
        <div class="transition-strip">
          {#each sec.transition_ids as trId, ti}
            {@const tr = getTransition(trId)}
            {#if tr}
              <div class="strip-item">
                <div class="strip-thumb" title="Transition {tr.position + 1}">
                  {#if tr.video_filename}
                    <img src="/api/projects/{projectId}/images/{tr.video_filename}?frame=0" alt="" />
                  {/if}
                  <span class="strip-num">{tr.position + 1}</span>
                </div>
                {#if ti < sec.transition_ids.length - 1}
                  <button class="split-btn" onclick={() => handleSplitAt(si, ti)}
                          title="Split here">
                    <Scissors size={12} />
                  </button>
                {/if}
              </div>
            {/if}
          {/each}
        </div>

        <!-- Prompt + settings -->
        <div class="card-body">
          <div class="prompt-row">
            <textarea
              class="prompt-input"
              placeholder="Soundtrack tags: genre, mood, instruments..."
              bind:value={sec.prompt}
              rows="2"
            ></textarea>
            <button class="suggest-btn" onclick={() => handleSuggest(sec)}
                    disabled={suggesting[sec.id]}>
              <Sparkles size={14} /> {suggesting[sec.id] ? '...' : 'Suggest'}
            </button>
          </div>

          <div class="settings-row">
            <label>
              BPM
              <input type="number" min="40" max="300" bind:value={sec.bpm} class="num-input" />
            </label>
            <label>
              Key
              <select bind:value={sec.keyscale} class="key-select">
                {#each ['C major','C minor','D major','D minor','E major','E minor',
                        'F major','F minor','G major','G minor','A major','A minor',
                        'B major','B minor'] as k}
                  <option value={k}>{k}</option>
                {/each}
              </select>
            </label>
          </div>
        </div>

        <!-- Preview / render -->
        <div class="card-preview">
          {#if sec.status === 'done' && previewUrl(sec)}
            <!-- svelte-ignore a11y_media_has_caption -->
            <video src={previewUrl(sec)} controls onplay={handleVideoPlay}
                   onpause={handleVideoPause}></video>
          {:else if sec.status === 'rendering'}
            <div class="render-placeholder">
              <div class="spinner"></div>
              <span>Rendering soundtrack...</span>
            </div>
          {:else if sec.status === 'error'}
            <div class="render-placeholder error">
              <span>{sec.error_message || 'Error'}</span>
            </div>
          {/if}
        </div>

        <div class="card-actions">
          <button class="btn-render" onclick={() => handleRender(sec)}
                  disabled={sec.status === 'rendering' || !sec.prompt.trim()}>
            {#if sec.status === 'done'}
              <RefreshCw size={16} /> Re-render
            {:else}
              <Play size={16} /> Render
            {/if}
          </button>
        </div>
      </div>
    {/each}
  </div>
{:else}
  <div class="empty">
    <p>Approve all narration to proceed to soundtrack.</p>
  </div>
{/if}

<style>
  .toolbar {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-bottom: 12px;
  }

  .toolbar-btn {
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border);
    font-size: 13px;
    padding: 6px 14px;
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }

  .toolbar-btn:hover:not(:disabled) {
    color: var(--text-dim);
    border-color: var(--text-muted);
  }

  .sections {
    display: flex;
    flex-direction: column;
    gap: 20px;
    margin-bottom: 24px;
  }

  .section-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }

  .card-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
  }

  .position { font-weight: 700; font-size: 18px; color: var(--text); min-width: 24px; }
  .label { font-size: 13px; color: var(--text-muted); }

  .status-badge {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
    padding: 2px 8px; border-radius: 10px; font-weight: 500; margin-left: auto;
  }
  .status-badge.pending { background: var(--accent-bg); color: var(--accent); }
  .status-badge.rendering { background: var(--accent-bg); color: var(--accent-hover); }
  .status-badge.done { background: rgba(34, 197, 94, 0.15); color: var(--success); }
  .status-badge.error { background: rgba(239, 68, 68, 0.15); color: var(--error); }

  .transition-strip {
    display: flex;
    gap: 2px;
    padding: 10px 14px;
    background: var(--bg);
    overflow-x: auto;
    align-items: center;
  }

  .strip-item {
    display: flex;
    align-items: center;
    gap: 2px;
    flex-shrink: 0;
  }

  .strip-thumb {
    width: 60px;
    height: 34px;
    border-radius: 4px;
    overflow: hidden;
    background: var(--bg-card);
    position: relative;
  }

  .strip-thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .strip-num {
    position: absolute;
    bottom: 1px;
    right: 3px;
    font-size: 10px;
    color: white;
    text-shadow: 0 1px 2px rgba(0,0,0,0.8);
  }

  .split-btn {
    background: transparent;
    color: var(--text-muted);
    padding: 4px;
    border-radius: 4px;
    opacity: 0.4;
    transition: opacity 0.15s;
  }

  .split-btn:hover { opacity: 1; color: var(--warning); }

  .card-body { padding: 14px; }

  .prompt-row {
    display: flex;
    gap: 8px;
    margin-bottom: 10px;
  }

  .prompt-input {
    flex: 1;
    resize: vertical;
    font-size: 14px;
    line-height: 1.5;
  }

  .suggest-btn {
    background: var(--bg-card-hover);
    color: var(--text-dim);
    border: 1px solid var(--border);
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 13px;
    padding: 6px 12px;
    align-self: flex-start;
    white-space: nowrap;
  }

  .suggest-btn:hover:not(:disabled) { color: var(--text); border-color: var(--text-muted); }

  .settings-row {
    display: flex;
    gap: 16px;
    align-items: center;
  }

  .settings-row label {
    font-size: 13px;
    color: var(--text-dim);
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .num-input {
    width: 75px;
    text-align: center;
    font-size: 13px;
  }

  .key-select {
    font-family: inherit;
    font-size: 13px;
    color: var(--text);
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 4px 8px;
  }

  .card-preview {
    min-height: 0;
  }

  .card-preview video {
    width: 100%;
    display: block;
  }

  .render-placeholder {
    padding: 40px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    color: var(--text-muted);
    font-size: 13px;
    background: var(--bg);
  }

  .render-placeholder.error { color: var(--error); }

  .spinner {
    width: 24px; height: 24px;
    border: 3px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  .card-actions {
    display: flex;
    gap: 8px;
    padding: 10px 14px;
    border-top: 1px solid var(--border);
  }

  .btn-render {
    background: var(--accent);
    color: white;
    font-size: 13px;
    font-weight: 500;
    padding: 8px 18px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-left: auto;
  }

  .btn-render:hover:not(:disabled) { background: var(--accent-hover); }

  .empty {
    text-align: center;
    padding: 80px 20px;
    color: var(--text-muted);
    border: 2px dashed var(--border);
    border-radius: var(--radius-lg);
    margin-bottom: 24px;
  }
</style>
