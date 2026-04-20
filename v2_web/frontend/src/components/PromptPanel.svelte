<script>
  import { generateKeyframes, renderKeyframe } from '../lib/api.js';

  let { ongenerated, onstatus } = $props();

  let theme = $state('');
  let count = $state(6);
  let generating = $state(false);

  async function handleGenerate() {
    if (!theme.trim()) return;
    generating = true;
    onstatus({ detail: 'Generating keyframe descriptions...' });

    try {
      const data = await generateKeyframes(theme.trim(), count);
      const newKeyframes = data.keyframes;
      ongenerated({ detail: newKeyframes });

      // Only render the first keyframe
      if (newKeyframes.length > 0) {
        onstatus({ detail: `Generated ${newKeyframes.length} keyframes. Rendering #1...` });
        renderKeyframe(newKeyframes[0].id).catch(e =>
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
