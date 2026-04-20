<script>
  import PromptPanel from './components/PromptPanel.svelte';
  import KeyframeGrid from './components/KeyframeGrid.svelte';
  import StatusBar from './components/StatusBar.svelte';
  import { listKeyframes } from './lib/api.js';

  let keyframes = $state([]);
  let statusMessage = $state('');

  async function refreshKeyframes() {
    try {
      const data = await listKeyframes();
      keyframes = data.keyframes;
    } catch (e) {
      statusMessage = `Error: ${e.message}`;
    }
  }

  function handleGenerated(event) {
    keyframes = [...keyframes, ...event.detail];
    statusMessage = `Generated ${event.detail.length} keyframes`;
  }

  function handleUpdated() {
    refreshKeyframes();
  }

  function handleStatus(event) {
    statusMessage = event.detail;
  }
</script>

<header>
  <h1>Film Director</h1>
  <p class="subtitle">Keyframe-driven video production with ComfyUI</p>
</header>

<PromptPanel
  ongenerated={handleGenerated}
  onstatus={handleStatus}
/>

<KeyframeGrid
  bind:keyframes
  onupdated={handleUpdated}
  onstatus={handleStatus}
/>

<StatusBar message={statusMessage} />

<style>
  header {
    margin-bottom: 32px;
  }

  h1 {
    font-size: 28px;
    font-weight: 600;
    margin-bottom: 4px;
  }

  .subtitle {
    color: var(--text-dim);
    font-size: 15px;
  }
</style>
