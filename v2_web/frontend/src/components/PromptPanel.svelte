<script>
  import { generateKeyframes, renderKeyframe } from '../lib/api.js';

  let { onproject, onstatus, projectName = '' } = $props();

  let theme = $state('');
  let count = $state(6);
  let generating = $state(false);

  async function handleGenerate() {
    if (!theme.trim()) return;
    generating = true;
    onstatus({ detail: 'Generating story and project name...' });

    try {
      const data = await generateKeyframes(theme.trim(), count);
      const project = data.project;
      onproject({ detail: project });
      onstatus({ detail: `Created "${project.name}" with ${project.keyframes.length} scenes. Rendering #1...` });

      if (project.keyframes.length > 0) {
        renderKeyframe(project.keyframes[0].id).catch(e =>
          onstatus({ detail: `Render error: ${e.message}` })
        );
      }
    } catch (e) {
      onstatus({ detail: `Generation failed: ${e.message}` });
    } finally {
      generating = false;
    }
  }

  function handleKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleGenerate();
    }
  }
</script>

<div class="premise-page">
  <div class="section">
    <h2>Initial Conditions</h2>
    <p class="hint">Describe the setting, characters, and situation. The story will evolve from here.</p>
    <textarea
      placeholder="A lighthouse keeper on a remote island discovers a locked door in the basement that wasn't there yesterday..."
      bind:value={theme}
      onkeydown={handleKeydown}
      disabled={generating}
      class="theme-input"
      rows="4"
    ></textarea>
  </div>

  <div class="controls">
    <div class="count-control">
      <label for="count">Scenes</label>
      <input
        id="count"
        type="number"
        min="2"
        max="24"
        bind:value={count}
        disabled={generating}
        class="count-input"
      />
      <span class="count-hint">
        {#if count <= 5}compressed arc{:else if count <= 10}standard arc{:else if count <= 16}extended arc{:else}epic arc{/if}
      </span>
    </div>

    <button
      onclick={handleGenerate}
      disabled={generating || !theme.trim()}
      class="generate-btn"
    >
      {generating ? 'Generating...' : 'Generate Story'}
    </button>
  </div>

  {#if projectName}
    <div class="existing-project">
      Note: generating will create a new project, replacing the current one ({projectName}).
    </div>
  {/if}
</div>

<style>
  .premise-page {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 28px;
  }

  .section {
    margin-bottom: 24px;
  }

  h2 {
    font-size: 18px;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 6px;
  }

  .hint {
    font-size: 13px;
    color: var(--text-muted);
    margin-bottom: 12px;
  }

  .theme-input {
    width: 100%;
    resize: vertical;
    line-height: 1.6;
    font-size: 15px;
  }

  .controls {
    display: flex;
    align-items: end;
    gap: 16px;
  }

  .count-control {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .count-control label {
    font-size: 14px;
    color: var(--text-dim);
  }

  .count-input {
    width: 65px;
    text-align: center;
  }

  .count-hint {
    font-size: 12px;
    color: var(--text-muted);
    font-style: italic;
  }

  .generate-btn {
    background: var(--accent);
    color: white;
    font-weight: 500;
    padding: 10px 28px;
    white-space: nowrap;
    font-size: 15px;
    margin-left: auto;
  }

  .generate-btn:hover:not(:disabled) {
    background: var(--accent-hover);
  }

  .existing-project {
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
    font-size: 13px;
    color: var(--text-muted);
  }
</style>
