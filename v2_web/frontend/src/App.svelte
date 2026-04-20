<script>
  import TabBar from './components/TabBar.svelte';
  import PromptPanel from './components/PromptPanel.svelte';
  import KeyframeGrid from './components/KeyframeGrid.svelte';
  import PlaceholderPage from './components/PlaceholderPage.svelte';
  import ProjectSelector from './components/ProjectSelector.svelte';
  import StatusBar from './components/StatusBar.svelte';
  import { getCurrentProject, renderKeyframe } from './lib/api.js';

  const tabs = [
    { id: 'premise', label: 'Premise' },
    { id: 'story', label: 'Story' },
    { id: 'keyframes', label: 'Keyframes' },
    { id: 'narration', label: 'Narration' },
    { id: 'transitions', label: 'Transitions' },
    { id: 'final', label: 'Final' },
  ];

  let activeTab = $state('premise');
  let keyframes = $state([]);
  let projectId = $state('');
  let projectName = $state('');
  let projectTheme = $state('');
  let activeIndex = $state(0);
  let statusMessage = $state('');
  let gridRef = $state(null);

  let projectLoaded = $derived(!!projectId);

  async function init() {
    try {
      const data = await getCurrentProject();
      if (data.project) {
        applyProject(data.project);
        // If there are keyframes, jump to the keyframes tab
        if (data.project.keyframes.length > 0) {
          activeTab = 'keyframes';
        }
      }
    } catch {
      // No project loaded yet
    }
  }

  function applyProject(project) {
    projectId = project.id;
    projectName = project.name;
    projectTheme = project.theme;
    keyframes = project.keyframes;
    activeIndex = project.active_index || 0;
    if (gridRef) {
      gridRef.setActive(activeIndex);
    }
  }

  function handleProject(event) {
    applyProject(event.detail);
    // Auto-navigate to keyframes tab
    activeTab = 'keyframes';
  }

  function handleLoadProject(event) {
    const project = event.detail;
    applyProject(project);
    if (project.keyframes.length > 0) {
      activeTab = 'keyframes';
    } else {
      activeTab = 'premise';
    }
    if (activeIndex < keyframes.length) {
      const kf = keyframes[activeIndex];
      if (kf.status === 'pending') {
        renderKeyframe(kf.id).catch(e =>
          statusMessage = `Render error: ${e.message}`
        );
      }
    }
  }

  function handleUpdated() {}

  function handleStatus(event) {
    statusMessage = event.detail;
  }

  init();
</script>

<header>
  <div class="header-row">
    <div>
      <h1>Film Director</h1>
      {#if projectName}
        <p class="subtitle">{projectName}</p>
      {:else}
        <p class="subtitle">Keyframe-driven video production with ComfyUI</p>
      {/if}
    </div>
    <ProjectSelector onload={handleLoadProject} onstatus={handleStatus} />
  </div>
</header>

<TabBar {tabs} bind:active={activeTab} {projectLoaded} />

<main>
  {#if activeTab === 'premise'}
    <PromptPanel
      onproject={handleProject}
      onstatus={handleStatus}
      {projectName}
    />

  {:else if activeTab === 'story'}
    <PlaceholderPage
      title="Story"
      description="View and edit the generated story arc, scene descriptions, and narrative beats."
    />

  {:else if activeTab === 'keyframes'}
    <KeyframeGrid
      bind:this={gridRef}
      bind:keyframes
      {projectId}
      onupdated={handleUpdated}
      onstatus={handleStatus}
    />

  {:else if activeTab === 'narration'}
    <PlaceholderPage
      title="Narration"
      description="Add voiceover narration to each scene from prompts or by editing generated text."
    />

  {:else if activeTab === 'transitions'}
    <PlaceholderPage
      title="Transitions"
      description="Preview and render video transitions between locked keyframes."
    />

  {:else if activeTab === 'final'}
    <PlaceholderPage
      title="Final"
      description="Preview the full sequence, add soundtrack, and render the final film."
    />
  {/if}
</main>

<StatusBar message={statusMessage} />

<style>
  header {
    margin-bottom: 24px;
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

  main {
    min-height: 300px;
  }
</style>
