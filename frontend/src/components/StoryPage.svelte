<script>
  import { Lock } from 'lucide-svelte';
  import { generateStory } from '../lib/api.js';

  let { onstatus, onstory, premise = '', locked = false, scenes = [],
        projectWidth = 1024, projectHeight = 576, projectSceneCount = 6,
        projectSceneDuration = 10 } = $props();

  let sceneCount = $state(6);
  let sceneDuration = $state(10);
  let generating = $state(false);

  let arcLabel = $derived(
    sceneCount <= 5 ? 'compressed arc' :
    sceneCount <= 10 ? 'standard arc' :
    sceneCount <= 16 ? 'extended arc' : 'epic arc'
  );

  let totalDuration = $derived(sceneCount * sceneDuration);
  let durationLabel = $derived(
    totalDuration < 60 ? `${totalDuration}s` :
    `${Math.floor(totalDuration / 60)}m ${totalDuration % 60}s`
  );

  async function handleGenerate() {
    generating = true;
    onstatus({ detail: `Generating ${sceneCount}-scene story...` });
    try {
      const data = await generateStory(sceneCount, sceneDuration, projectWidth, projectHeight);
      onstory({ detail: data.project });
      onstatus({ detail: `Story generated with ${data.project.keyframes.length} scenes. Proceed to Keyframes.` });
    } catch (e) {
      onstatus({ detail: `Story generation failed: ${e.message}` });
    } finally {
      generating = false;
    }
  }
</script>

<div class="story-page" class:locked>
  {#if locked}
    <div class="locked-banner">
      <Lock size={14} /> Story is locked. Go to the Keyframes tab to continue.
    </div>
  {/if}

  {#if premise}
    <div class="premise-summary">
      <span class="label">Premise</span>
      <p>{premise}</p>
    </div>
  {/if}

  {#if locked}
    <div class="settings-summary">
      <span class="setting"><strong>{projectSceneCount}</strong> scenes</span>
      <span class="sep">&middot;</span>
      <span class="setting"><strong>{projectSceneDuration}s</strong> per scene</span>
      <span class="sep">&middot;</span>
      <span class="setting"><strong>{projectWidth}&times;{projectHeight}</strong></span>
      <span class="sep">&middot;</span>
      <span class="setting">~{Math.floor(projectSceneCount * projectSceneDuration / 60)}m {projectSceneCount * projectSceneDuration % 60}s total</span>
    </div>
  {/if}

  {#if !locked}
    <div class="controls">
      <div class="control-group">
        <label for="scene-count">Scenes</label>
        <input id="scene-count" type="number" min="2" max="24"
               bind:value={sceneCount} disabled={generating} class="num-input" />
        <span class="hint">{arcLabel}</span>
      </div>
      <div class="control-group">
        <label for="scene-dur">Duration per scene</label>
        <input id="scene-dur" type="number" min="3" max="60"
               bind:value={sceneDuration} disabled={generating} class="num-input" />
        <span class="hint">seconds</span>
      </div>
      <div class="control-group">
        <span class="total">Total: ~{durationLabel}</span>
      </div>
      <button class="generate-btn" onclick={handleGenerate} disabled={generating}>
        {generating ? 'Generating...' : 'Generate Story'}
      </button>
    </div>
  {/if}

  {#if scenes.length > 0}
    <div class="scene-list">
      <h2>Scenes</h2>
      {#each scenes as scene, i}
        <div class="scene-item">
          <span class="scene-num">{i + 1}</span>
          <p class="scene-text">{scene.prompt}</p>
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .story-page {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 28px;
  }

  .story-page.locked {
    opacity: 0.7;
  }

  .locked-banner {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 10px 14px;
    background: var(--accent-bg);
    color: var(--accent);
    border-radius: var(--radius);
    font-size: 13px;
    font-weight: 500;
    margin-bottom: 20px;
  }

  .premise-summary {
    margin-bottom: 24px;
    padding: 16px;
    background: var(--bg);
    border-radius: var(--radius);
    border: 1px solid var(--border);
  }

  .premise-summary .label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    display: block;
    margin-bottom: 6px;
  }

  .premise-summary p {
    font-size: 14px;
    color: var(--text-dim);
    line-height: 1.6;
  }

  .settings-summary {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: 20px;
    font-size: 14px;
    color: var(--text-dim);
  }

  .settings-summary strong {
    color: var(--text);
  }

  .sep {
    color: var(--text-muted);
  }

  .controls {
    display: flex;
    align-items: end;
    gap: 20px;
    flex-wrap: wrap;
    margin-bottom: 24px;
  }

  .control-group {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .control-group label {
    font-size: 14px;
    color: var(--text-dim);
    white-space: nowrap;
  }

  .num-input {
    width: 65px;
    text-align: center;
  }

  .hint {
    font-size: 12px;
    color: var(--text-muted);
    font-style: italic;
  }

  .total {
    font-size: 14px;
    color: var(--text-dim);
    font-weight: 500;
  }

  .generate-btn {
    background: var(--accent);
    color: white;
    font-weight: 500;
    padding: 10px 28px;
    font-size: 15px;
    margin-left: auto;
  }

  .generate-btn:hover:not(:disabled) {
    background: var(--accent-hover);
  }

  .scene-list {
    margin-top: 4px;
  }

  .scene-list h2 {
    font-size: 16px;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 12px;
  }

  .scene-item {
    display: flex;
    gap: 12px;
    padding: 12px 0;
    border-bottom: 1px solid var(--border);
  }

  .scene-item:last-child {
    border-bottom: none;
  }

  .scene-num {
    font-weight: 700;
    font-size: 16px;
    color: var(--text-muted);
    min-width: 28px;
    text-align: right;
    flex-shrink: 0;
  }

  .scene-text {
    font-size: 14px;
    color: var(--text-dim);
    line-height: 1.5;
  }
</style>
