<script>
  import PromptPanel from './components/PromptPanel.svelte';
  import KeyframeGrid from './components/KeyframeGrid.svelte';
  import ProjectSelector from './components/ProjectSelector.svelte';
  import StatusBar from './components/StatusBar.svelte';
  import { getCurrentProject, renderKeyframe } from './lib/api.js';

  let keyframes = $state([]);
  let projectId = $state('');
  let projectName = $state('');
  let activeIndex = $state(0);
  let statusMessage = $state('');
  let gridRef = $state(null);

  // Load last project on startup
  async function init() {
    try {
      const data = await getCurrentProject();
      if (data.project) {
        applyProject(data.project);
      }
    } catch {
      // No project loaded yet, that's fine
    }
  }

  function applyProject(project) {
    projectId = project.id;
    projectName = project.name;
    keyframes = project.keyframes;
    activeIndex = project.active_index || 0;
    if (gridRef) {
      gridRef.setActive(activeIndex);
    }
  }

  function handleProject(event) {
    applyProject(event.detail);
    // First keyframe render was already triggered by PromptPanel
  }

  function handleLoadProject(event) {
    const project = event.detail;
    applyProject(project);
    // If active keyframe needs rendering, kick it off
    if (activeIndex < keyframes.length) {
      const kf = keyframes[activeIndex];
      if (kf.status === 'pending') {
        renderKeyframe(kf.id).catch(e =>
          statusMessage = `Render error: ${e.message}`
        );
      }
    }
  }

  function handleUpdated() {
    // Keyframes are mutated in place; no need to refetch
  }

  function handleStatus(event) {
    statusMessage = event.detail;
  }

  init();
</script>

<header>
  <div class="header-row">
    <div>
      <h1>Film Director</h1>
      <p class="subtitle">Keyframe-driven video production with ComfyUI</p>
    </div>
    <ProjectSelector onload={handleLoadProject} onstatus={handleStatus} />
  </div>
</header>

<PromptPanel
  onproject={handleProject}
  onstatus={handleStatus}
  {projectName}
/>

<KeyframeGrid
  bind:this={gridRef}
  bind:keyframes
  {projectId}
  onupdated={handleUpdated}
  onstatus={handleStatus}
/>

<StatusBar message={statusMessage} />

<style>
  header {
    margin-bottom: 32px;
  }

  .header-row {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: 16px;
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
