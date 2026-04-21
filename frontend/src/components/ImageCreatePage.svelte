<script>
  import { Sparkles, Plus } from 'lucide-svelte';
  import { createProject, addKeyframe, renderKeyframe } from '../lib/api.js';

  let { project = $bindable(null), onstatus, ongallery } = $props();

  let prompt = $state('');
  let generating = $state(false);

  async function handleGenerate() {
    if (!prompt.trim()) return;
    generating = true;
    try {
      // Create a project if we don't have one yet
      if (!project) {
        const data = await createProject('image-generator', 'Untitled Gallery');
        project = data.project;
      }
      // Add a keyframe with this prompt and render it
      const kf = await addKeyframe(prompt.trim());
      project.keyframes = [...(project.keyframes || []), kf];
      kf.status = 'rendering';
      onstatus?.({ detail: 'Generating image...' });
      renderKeyframe(kf.id).then(() => {
        onstatus?.({ detail: 'Image generated.' });
      }).catch(e => {
        onstatus?.({ detail: `Render error: ${e.message}` });
      });
      // Switch to gallery to watch it render
      ongallery?.();
    } catch (e) {
      onstatus?.({ detail: `Failed: ${e.message}` });
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

<div class="create-page">
  <div class="section">
    <h2>Generate an Image</h2>
    <p class="hint">Describe the image you want to create.</p>
    <textarea
      placeholder="A vast desert landscape at golden hour, ancient ruins half-buried in sand, dramatic clouds..."
      bind:value={prompt}
      disabled={generating}
      onkeydown={handleKeydown}
      class="prompt-input"
      rows="4"
    ></textarea>
    <div class="actions">
      <button class="generate-btn" onclick={handleGenerate}
              disabled={generating || !prompt.trim()}>
        <Sparkles size={16} />
        {generating ? 'Creating...' : 'Generate'}
      </button>
    </div>
  </div>
</div>

<style>
  .create-page {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 28px;
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

  .prompt-input {
    width: 100%;
    resize: vertical;
    line-height: 1.6;
    font-size: 15px;
    margin-bottom: 12px;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
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
</style>
