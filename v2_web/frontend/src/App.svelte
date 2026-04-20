<script>
  import TabBar from './components/TabBar.svelte';
  import PremisePage from './components/PremisePage.svelte';
  import StoryPage from './components/StoryPage.svelte';
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
  let project = $state(null);
  let statusMessage = $state('');
  let gridRef = $state(null);
  let premiseRef = $state(null);

  // Derived state from project
  let projectId = $derived(project?.id || '');
  let projectName = $derived(project?.name || '');
  let premise = $derived(project?.premise || '');
  let premiseLocked = $derived(project?.premise_locked || false);
  let storyLocked = $derived(project?.story_locked || false);
  let keyframes = $derived(project?.keyframes || []);

  // Which tab is the furthest reachable?
  let enabledThrough = $derived(
    storyLocked ? 'keyframes' :
    premiseLocked ? 'story' :
    'premise'
  );

  async function init() {
    try {
      const data = await getCurrentProject();
      if (data.project) {
        project = data.project;
        // Jump to the furthest active tab
        if (data.project.story_locked && data.project.keyframes.length > 0) {
          activeTab = 'keyframes';
        } else if (data.project.premise_locked) {
          activeTab = 'story';
        }
      }
    } catch {
      // No project loaded yet
    }
  }

  function handlePremise(event) {
    project = event.detail;
    activeTab = 'story';
  }

  function handleStory(event) {
    project = event.detail;
    activeTab = 'keyframes';
    // Render the first keyframe and mark it rendering so polling starts
    if (project.keyframes.length > 0) {
      const kf = project.keyframes[0];
      kf.status = 'rendering';
      renderKeyframe(kf.id).catch(e =>
        statusMessage = `Render error: ${e.message}`
      );
    }
  }

  function handleLoadProject(event) {
    project = event.detail;
    if (project.story_locked && project.keyframes.length > 0) {
      activeTab = 'keyframes';
      const idx = project.active_index || 0;
      if (idx < project.keyframes.length) {
        const kf = project.keyframes[idx];
        if (kf.status === 'pending') {
          kf.status = 'rendering';
          renderKeyframe(kf.id).catch(e =>
            statusMessage = `Render error: ${e.message}`
          );
        }
      }
    } else if (project.premise_locked) {
      activeTab = 'story';
    } else {
      activeTab = 'premise';
      // Restore notes/premise into the form
      if (premiseRef) {
        premiseRef.setPremiseText(project.premise || '');
        premiseRef.setNotesText(project.notes || '');
      }
    }
  }

  function handleStatus(event) {
    statusMessage = event.detail;
  }

  function handleUpdated() {}

  // Sync keyframes mutations back into project
  let mutableKeyframes = $state([]);
  $effect(() => {
    if (project?.keyframes) {
      mutableKeyframes = project.keyframes;
    }
  });

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

<TabBar {tabs} bind:active={activeTab} {enabledThrough} />

<main>
  {#if activeTab === 'premise'}
    <PremisePage
      bind:this={premiseRef}
      onstatus={handleStatus}
      onpremise={handlePremise}
      locked={premiseLocked}
    />

  {:else if activeTab === 'story'}
    <StoryPage
      onstatus={handleStatus}
      onstory={handleStory}
      {premise}
      locked={storyLocked}
      scenes={keyframes}
    />

  {:else if activeTab === 'keyframes'}
    <KeyframeGrid
      bind:this={gridRef}
      bind:keyframes={mutableKeyframes}
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
