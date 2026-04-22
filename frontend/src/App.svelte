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
  import ActivityMenu from './components/ActivityMenu.svelte';
  import ImageCreatePage from './components/ImageCreatePage.svelte';
  import ImageGalleryPage from './components/ImageGalleryPage.svelte';
  import StatusBar from './components/StatusBar.svelte';
  import { getCurrentProject, renderKeyframe, renderTransition, renameProject, ACTIVITIES } from './lib/api.js';

  const ACTIVITY_TABS = {
    'film-director': [
      { id: 'premise', label: 'Premise' },
      { id: 'story', label: 'Story' },
      { id: 'keyframes', label: 'Keyframes' },
      { id: 'transitions', label: 'Transitions' },
      { id: 'narration', label: 'Narration' },
      { id: 'score', label: 'Score' },
      { id: 'final', label: 'Final' },
    ],
    'image-generator': [
      { id: 'create', label: 'Create' },
      { id: 'gallery', label: 'Gallery' },
    ],
  };

  let activity = $state('film-director');
  let tabs = $derived(ACTIVITY_TABS[activity] || ACTIVITY_TABS['film-director']);
  let activityLabel = $derived(ACTIVITIES.find(a => a.id === activity)?.label || 'Film Director');

  let activeTab = $state('premise');
  let project = $state(null);
  let statusMessage = $state('');
  let premiseRef = $state(null);
  let recreateImage = $state(null);
  let editingTitle = $state(false);
  let editTitle = $state('');

  let projectId = $derived(project?.id || '');
  let projectName = $derived(project?.name || '');
  let premise = $derived(project?.premise || '');
  let premiseLocked = $derived(project?.premise_locked || false);
  let storyLocked = $derived(project?.story_locked || false);
  let hasKeyframes = $derived((project?.keyframes || []).some(kf => kf.status === 'done'));
  let transitionsLocked = $derived(project?.transitions_locked || false);
  let narrationLocked = $derived(project?.narration_locked || false);
  let scoreLocked = $derived(project?.score_locked || false);
  let keyframes = $derived(project?.keyframes || []);
  let transitions = $derived(project?.transitions || []);
  let soundtrackSections = $derived(project?.soundtrack_sections || []);

  let hasTransitions = $derived(transitions.length > 0);
  let enabledThrough = $derived.by(() => {
    if (activity === 'image-generator') {
      return project ? 'gallery' : 'create';
    }
    // film-director
    return scoreLocked ? 'final' :
           narrationLocked ? 'score' :
           transitionsLocked ? 'narration' :
           (hasKeyframes || hasTransitions) ? 'transitions' :
           storyLocked ? 'keyframes' :
           premiseLocked ? 'story' :
           'premise';
  });

  async function init() {
    try {
      const data = await getCurrentProject();
      if (data.project) {
        project = data.project;
        activity = data.project.activity || 'film-director';
        activeTab = pickTab(data.project);
      }
    } catch {}
  }

  function pickTab(proj) {
    if (proj.activity === 'image-generator') {
      return proj.keyframes?.length > 0 ? 'gallery' : 'create';
    }
    // film-director
    if (proj.score_locked) return 'final';
    if (proj.narration_locked) return 'score';
    if (proj.transitions_locked) return 'narration';
    if (proj.transitions?.length > 0) return 'transitions';
    if (proj.story_locked && proj.keyframes?.length > 0) return 'keyframes';
    if (proj.premise_locked) return 'story';
    return 'premise';
  }

  function handlePremise(event) {
    project = event.detail;
    activeTab = 'story';
  }

  function handleSkipToKeyframes(event) {
    project = event.detail;
    activeTab = 'keyframes';
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

  function handleGoToTransitions(event) {
    project = event.detail;
    activeTab = 'transitions';
    // Render the first pending transition
    const pending = project.transitions.find(tr => tr.status === 'pending');
    if (pending) {
      pending.status = 'rendering';
      renderTransition(pending.id).catch(e => statusMessage = `Render error: ${e.message}`);
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
    activity = project.activity || 'film-director';
    activeTab = pickTab(project);
    // Auto-render pending keyframe if we land on keyframes tab
    if (activeTab === 'keyframes' && project.story_locked) {
      const idx = project.active_index || 0;
      if (idx < project.keyframes.length) {
        const kf = project.keyframes[idx];
        if (kf.status === 'pending') {
          kf.status = 'rendering';
          renderKeyframe(kf.id).catch(e => statusMessage = `Render error: ${e.message}`);
        }
      }
    }
    // Restore premise text if we're at premise tab
    if (activeTab === 'premise' && premiseRef) {
      premiseRef.setPremiseText(project.premise || '');
      premiseRef.setNotesText(project.notes || '');
    }
  }

  function defaultTab(act) {
    return act === 'image-generator' ? 'create' : 'premise';
  }

  function handleNewProject() {
    project = null;
    activeTab = defaultTab(activity);
    editingTitle = false;
    if (premiseRef) {
      premiseRef.setPremiseText('');
      premiseRef.setNotesText('');
    }
  }

  function handleActivityChange(event) {
    const newActivity = event.detail;
    if (project && (project.activity || 'film-director') !== newActivity) {
      project = null;
      editingTitle = false;
      if (premiseRef) {
        premiseRef.setPremiseText('');
        premiseRef.setNotesText('');
      }
    }
    activeTab = defaultTab(newActivity);
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
  $effect.pre(() => { if (project?.keyframes) mutableKeyframes = project.keyframes; });

  let mutableTransitions = $state([]);
  $effect.pre(() => { if (project?.transitions) mutableTransitions = project.transitions; });

  let mutableSections = $state([]);
  $effect.pre(() => { if (project?.soundtrack_sections) mutableSections = project.soundtrack_sections; });

  init();
</script>

<header>
  <div class="header-row">
    <div>
      {#if projectName}
        <p class="app-label">{activityLabel}</p>
        {#if editingTitle}
          <input class="title-edit" bind:value={editTitle}
                 onkeydown={handleTitleKeydown} onblur={saveTitle} autofocus />
        {:else}
          <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
          <h1 class="project-title clickable" onclick={startEditTitle} title="Click to rename">{projectName}</h1>
        {/if}
      {:else}
        <h1>{activityLabel}</h1>
        <p class="subtitle">{ACTIVITIES.find(a => a.id === activity)?.subtitle || ''}</p>
      {/if}
    </div>
    <div class="header-actions">
      <button class="new-btn" onclick={handleNewProject}>New</button>
      <ProjectSelector {activity} onload={handleLoadProject} onstatus={handleStatus} />
      <ActivityMenu bind:activity onchange={handleActivityChange} />
    </div>
  </div>
</header>

<TabBar {tabs} bind:active={activeTab} {enabledThrough} />

<main>
  {#if activeTab === 'premise'}
    <PremisePage bind:this={premiseRef} onstatus={handleStatus}
                 onpremise={handlePremise} onskip={handleSkipToKeyframes}
                 locked={premiseLocked} {activity} />

  {:else if activeTab === 'story'}
    <StoryPage onstatus={handleStatus} onstory={handleStory}
               {premise} locked={storyLocked} scenes={keyframes}
               projectWidth={project?.width || 1024} projectHeight={project?.height || 576}
               projectSceneCount={project?.scene_count || 6}
               projectSceneDuration={project?.scene_duration || 10} />

  {:else if activeTab === 'keyframes'}
    <KeyframeGrid bind:keyframes={mutableKeyframes}
                  {projectId}
                  projectWidth={project?.width || 1024}
                  projectHeight={project?.height || 576}
                  onupdated={handleUpdated} onstatus={handleStatus}
                  onreset={(e) => { project = e.detail; }}
                  ongotransitions={handleGoToTransitions}
                  onsync={(e) => {
                    if (e.detail.id) { project = e.detail; }
                    else if (e.detail.transitions && project) { project.transitions = e.detail.transitions; }
                  }} />

  {:else if activeTab === 'transitions'}
    <TransitionsPage bind:transitions={mutableTransitions}
                     keyframes={keyframes} {projectId}
                     locked={transitionsLocked}
                     projectSceneDuration={project?.scene_duration || 10}
                     onstatus={handleStatus}
                     onreset={(e) => { project = e.detail; }}
                     onlocktransitions={handleLockTransitions} />

  {:else if activeTab === 'narration'}
    <NarrationPage bind:transitions={mutableTransitions}
                   keyframes={keyframes} {projectId}
                   direction={project?.narration_direction || ''}
                   defaultVoice={project?.narration_voice || ''}
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

  {:else if activeTab === 'create'}
    <ImageCreatePage bind:project onstatus={handleStatus}
                     ongallery={() => activeTab = 'gallery'}
                     bind:recreateImage />

  {:else if activeTab === 'gallery'}
    <ImageGalleryPage {projectId} onstatus={handleStatus}
                      oncreate={() => activeTab = 'create'}
                      onrecreate={(e) => { recreateImage = e.detail; activeTab = 'create'; }} />
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
