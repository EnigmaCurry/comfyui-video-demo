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

      // Render the first keyframe
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

<div class="prompt-panel">
  {#if projectName}
    <div class="current-project">
      <span class="project-label">Project:</span>
      <span class="project-name">{projectName}</span>
    </div>
  {/if}
  <div class="input-row">
    <textarea
      placeholder="Describe the setting, characters, and situation to begin your story..."
      bind:value={theme}
      onkeydown={handleKeydown}
      disabled={generating}
      class="theme-input"
      rows="2"
    ></textarea>
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
    </div>
    <button
      onclick={handleGenerate}
      disabled={generating || !theme.trim()}
      class="generate-btn"
    >
      {generating ? 'Generating...' : 'Generate'}
    </button>
  </div>
</div>

<style>
  .prompt-panel {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 20px;
    margin-bottom: 24px;
  }

  .current-project {
    margin-bottom: 12px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
  }

  .project-label {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin-right: 8px;
  }

  .project-name {
    font-weight: 600;
    color: var(--text);
  }

  .input-row {
    display: flex;
    gap: 12px;
    align-items: end;
  }

  .theme-input {
    flex: 1;
    min-width: 0;
    resize: vertical;
    line-height: 1.5;
  }

  .count-control {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .count-control label {
    font-size: 12px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .count-input {
    width: 70px;
    text-align: center;
  }

  .generate-btn {
    background: var(--accent);
    color: white;
    font-weight: 500;
    padding: 10px 24px;
    white-space: nowrap;
  }

  .generate-btn:hover:not(:disabled) {
    background: var(--accent-hover);
  }
</style>
