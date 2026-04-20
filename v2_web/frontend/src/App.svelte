<script>
  import TabBar from './components/TabBar.svelte';
  import PremisePage from './components/PremisePage.svelte';
  import StoryPage from './components/StoryPage.svelte';
  import KeyframeGrid from './components/KeyframeGrid.svelte';
  import TransitionsPage from './components/TransitionsPage.svelte';
  import NarrationPage from './components/NarrationPage.svelte';
  import FinalPage from './components/FinalPage.svelte';
  import RenderPage from './components/RenderPage.svelte';
  import ProjectSelector from './components/ProjectSelector.svelte';
  import StatusBar from './components/StatusBar.svelte';
  import { getCurrentProject, renderKeyframe, renderTransition, renameProject } from './lib/api.js';

  const tabs = [
    { id: 'premise', label: 'Premise' },
    { id: 'story', label: 'Story' },
    { id: 'keyframes', label: 'Keyframes' },
    { id: 'transitions', label: 'Transitions' },
    { id: 'narration', label: 'Narration' },
    { id: 'score', label: 'Score' },
    { id: 'final', label: 'Final' },
  ];

  let activeTab = $state('premise');
  let project = $state(null);
  let statusMessage = $state('');
  let gridRef = $state(null);
  let premiseRef = $state(null);
  let editingTitle = $state(false);
  let editTitle = $state('');

  let projectId = $derived(project?.id || '');
  let projectName = $derived(project?.name || '');
  let premise = $derived(project?.premise || '');
  let premiseLocked = $derived(project?.premise_locked || false);
  let storyLocked = $derived(project?.story_locked || false);
  let keyframesLocked = $derived(project?.keyframes_locked || false);
  let transitionsLocked = $derived(project?.transitions_locked || false);
  let narrationLocked = $derived(project?.narration_locked || false);
  let scoreLocked = $derived(project?.score_locked || false);
  let keyframes = $derived(project?.keyframes || []);
  let transitions = $derived(project?.transitions || []);
  let soundtrackSections = $derived(project?.soundtrack_sections || []);

  let enabledThrough = $derived(
    scoreLocked ? 'final' :
    narrationLocked ? 'score' :
    transitionsLocked ? 'narration' :
    keyframesLocked ? 'transitions' :
    storyLocked ? 'keyframes' :
    premiseLocked ? 'story' :
    'premise'
  );

  async function init() {
    try {
      const data = await getCurrentProject();
      if (data.project) {
        project = data.project;
        if (data.project.score_locked) {
          activeTab = 'final';
        } else if (data.project.narration_locked) {
          activeTab = 'score';
        } else if (data.project.transitions_locked) {
          activeTab = 'narration';
        } else if (data.project.keyframes_locked && data.project.transitions?.length > 0) {
          activeTab = 'transitions';
        } else if (data.project.story_locked && data.project.keyframes.length > 0) {
          activeTab = 'keyframes';
        } else if (data.project.premise_locked) {
          activeTab = 'story';
        }
      }
    } catch {}
  }

  function handlePremise(event) {
    project = event.detail;
    activeTab = 'story';
  }

  function handleStory(event) {
    project = event.detail;
    activeTab = 'keyframes';
    if (project.keyframes.length > 0) {
      const kf = project.keyframes[0];
      kf.status = 'rendering';
      renderKeyframe(kf.id).catch(e => statusMessage = `Render error: ${e.message}`);
    }
  }

  function handleLockKeyframes(event) {
    project = event.detail;
    activeTab = 'transitions';
    // Render the first transition
    if (project.transitions.length > 0) {
      const tr = project.transitions[0];
      tr.status = 'rendering';
      renderTransition(tr.id).catch(e => statusMessage = `Render error: ${e.message}`);
    }
  }

  function handleLockTransitions(event) {
    project = event.detail;
    activeTab = 'narration';
  }

  function handleLockNarration(event) {
    project = event.detail;
    activeTab = 'score';
  }

  function handleLockScore(event) {
    project = event.detail;
    activeTab = 'final';
  }

  function handleLoadProject(event) {
    project = event.detail;
    if (project.score_locked) {
      activeTab = 'final';
    } else if (project.narration_locked) {
      activeTab = 'score';
    } else if (project.transitions_locked) {
      activeTab = 'narration';
    } else if (project.keyframes_locked && project.transitions?.length > 0) {
      activeTab = 'transitions';
    } else if (project.story_locked && project.keyframes.length > 0) {
      activeTab = 'keyframes';
      const idx = project.active_index || 0;
      if (idx < project.keyframes.length) {
        const kf = project.keyframes[idx];
        if (kf.status === 'pending') {
          kf.status = 'rendering';
          renderKeyframe(kf.id).catch(e => statusMessage = `Render error: ${e.message}`);
        }
      }
    } else if (project.premise_locked) {
      activeTab = 'story';
    } else {
      activeTab = 'premise';
      if (premiseRef) {
        premiseRef.setPremiseText(project.premise || '');
        premiseRef.setNotesText(project.notes || '');
      }
    }
  }

  function handleNewProject() {
    project = null;
    activeTab = 'premise';
    editingTitle = false;
    if (premiseRef) {
      premiseRef.setPremiseText('');
      premiseRef.setNotesText('');
    }
  }

  let statusTimer = null;
  function handleStatus(event) {
    statusMessage = event.detail;
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => { statusMessage = ''; }, 8000);
  }
  function handleUpdated() {}

  function startEditTitle() {
    editTitle = projectName;
    editingTitle = true;
  }

  async function saveTitle() {
    if (editTitle.trim() && editTitle !== projectName) {
      try {
        await renameProject(editTitle.trim());
        project.name = editTitle.trim();
      } catch (e) { statusMessage = `Rename failed: ${e.message}`; }
    }
    editingTitle = false;
  }

  function handleTitleKeydown(e) {
    if (e.key === 'Enter') { e.preventDefault(); saveTitle(); }
    else if (e.key === 'Escape') { editingTitle = false; }
  }

  $effect(() => { activeTab; window.scrollTo(0, 0); });

  let mutableKeyframes = $state([]);
  $effect(() => { if (project?.keyframes) mutableKeyframes = project.keyframes; });

  let mutableTransitions = $state([]);
  $effect(() => { if (project?.transitions) mutableTransitions = project.transitions; });

  let mutableSections = $state([]);
  $effect(() => { if (project?.soundtrack_sections) mutableSections = project.soundtrack_sections; });

  init();
</script>

<header>
  <div class="header-row">
    <div>
      {#if projectName}
        <p class="app-label">Film Director</p>
        {#if editingTitle}
          <input class="title-edit" bind:value={editTitle}
                 onkeydown={handleTitleKeydown} onblur={saveTitle} autofocus />
        {:else}
          <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
          <h1 class="project-title clickable" onclick={startEditTitle} title="Click to rename">{projectName}</h1>
        {/if}
      {:else}
        <h1>Film Director</h1>
        <p class="subtitle">Keyframe-driven video production with ComfyUI</p>
      {/if}
    </div>
    <div class="header-actions">
      <button class="new-btn" onclick={handleNewProject}>New</button>
      <ProjectSelector onload={handleLoadProject} onstatus={handleStatus} />
    </div>
  </div>
</header>

<TabBar {tabs} bind:active={activeTab} {enabledThrough} />

<main>
  {#if activeTab === 'premise'}
    <PremisePage bind:this={premiseRef} onstatus={handleStatus}
                 onpremise={handlePremise} locked={premiseLocked} />

  {:else if activeTab === 'story'}
    <StoryPage onstatus={handleStatus} onstory={handleStory}
               {premise} locked={storyLocked} scenes={keyframes} />

  {:else if activeTab === 'keyframes'}
    <KeyframeGrid bind:this={gridRef} bind:keyframes={mutableKeyframes}
                  {projectId} locked={keyframesLocked}
                  onupdated={handleUpdated} onstatus={handleStatus}
                  onreset={(e) => { project = e.detail; }}
                  onlockkeyframes={handleLockKeyframes} />

  {:else if activeTab === 'transitions'}
    <TransitionsPage bind:transitions={mutableTransitions}
                     keyframes={keyframes} {projectId}
                     locked={transitionsLocked}
                     onstatus={handleStatus}
                     onreset={(e) => { project = e.detail; }}
                     onlocktransitions={handleLockTransitions} />

  {:else if activeTab === 'narration'}
    <NarrationPage bind:transitions={mutableTransitions}
                   keyframes={keyframes} {projectId}
                   direction={project?.narration_direction || ''}
                   onstatus={handleStatus}
                   onreset={(e) => { project = e.detail; }}
                   onlocknarration={handleLockNarration} />

  {:else if activeTab === 'score'}
    <FinalPage bind:sections={mutableSections}
               transitions={transitions} {projectId}
               onstatus={handleStatus}
               onreset={(e) => {
                 if (e.detail.soundtrack_sections) {
                   project.soundtrack_sections = e.detail.soundtrack_sections;
                 } else {
                   project = e.detail;
                 }
               }}
               onlockscore={handleLockScore} />

  {:else if activeTab === 'final'}
    <RenderPage {projectId} projectName={projectName} onstatus={handleStatus} />
  {/if}
</main>

<StatusBar message={statusMessage} />

<style>
  header { margin-bottom: 24px; }

  .header-row {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: 16px;
  }

  h1 { font-size: 28px; font-weight: 600; margin-bottom: 4px; }

  .app-label {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
    margin-bottom: 2px;
  }

  .project-title { font-size: 28px; font-weight: 600; margin-bottom: 4px; }

  .project-title.clickable {
    cursor: pointer;
    border-bottom: 1px dashed transparent;
    transition: border-color 0.15s;
  }

  .project-title.clickable:hover { border-bottom-color: var(--text-muted); }

  .subtitle { color: var(--text-dim); font-size: 15px; }

  .title-edit {
    font-size: 24px;
    font-weight: 600;
    padding: 2px 6px;
    margin: 0;
    width: 400px;
  }

  .header-actions { display: flex; gap: 8px; align-items: center; }

  .new-btn {
    background: transparent;
    color: var(--text-dim);
    border: 1px solid var(--border);
    font-size: 13px;
    padding: 6px 12px;
  }

  .new-btn:hover { color: var(--text); border-color: var(--text-muted); }

  main { min-height: 300px; }
</style>
