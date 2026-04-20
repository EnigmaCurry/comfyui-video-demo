<script>
  import { FolderOpen, Trash2, X } from 'lucide-svelte';
  import { listProjects, loadProject, deleteProject } from '../lib/api.js';

  let { onload, onstatus } = $props();

  let open = $state(false);
  let projects = $state([]);
  let loading = $state(false);

  async function fetchProjects() {
    loading = true;
    try {
      const data = await listProjects();
      projects = data.projects;
    } catch (e) {
      onstatus({ detail: `Failed to load projects: ${e.message}` });
    } finally {
      loading = false;
    }
  }

  async function handleOpen() {
    open = true;
    await fetchProjects();
  }

  async function handleLoad(id) {
    try {
      const data = await loadProject(id);
      onload({ detail: data.project });
      open = false;
      onstatus({ detail: `Loaded project: ${data.project.name}` });
    } catch (e) {
      onstatus({ detail: `Failed to load project: ${e.message}` });
    }
  }

  async function handleDelete(e, id, name) {
    e.stopPropagation();
    if (!confirm(`Delete project "${name}"? This cannot be undone.`)) return;
    try {
      await deleteProject(id);
      projects = projects.filter(p => p.id !== id);
      onstatus({ detail: `Deleted project: ${name}` });
    } catch (err) {
      onstatus({ detail: `Delete failed: ${err.message}` });
    }
  }

  function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }
</script>

<button class="load-btn" onclick={handleOpen}>
  <FolderOpen size={16} /> Load Project
</button>

{#if open}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="overlay" onclick={() => open = false}>
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div class="modal" onclick={(e) => e.stopPropagation()}>
      <div class="modal-header">
        <h2>Load Project</h2>
        <button class="close-btn" onclick={() => open = false}><X size={18} /></button>
      </div>
      <div class="modal-body">
        {#if loading}
          <p class="loading">Loading...</p>
        {:else if projects.length === 0}
          <p class="empty">No saved projects yet.</p>
        {:else}
          {#each projects as proj}
            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
            <div class="project-row" onclick={() => handleLoad(proj.id)}>
              <div class="project-info">
                <span class="project-name">{proj.name}</span>
                <span class="project-meta">
                  {proj.keyframe_count} scenes &middot; {formatDate(proj.updated_at)}
                </span>
              </div>
              <button class="delete-btn" onclick={(e) => handleDelete(e, proj.id, proj.name)}
                      title="Delete project">
                <Trash2 size={14} />
              </button>
            </div>
          {/each}
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  .load-btn {
    background: transparent;
    color: var(--text-dim);
    border: 1px solid var(--border);
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    padding: 6px 12px;
  }

  .load-btn:hover {
    color: var(--text);
    border-color: var(--text-muted);
  }

  .overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.7);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
  }

  .modal {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    width: 480px;
    max-width: 90vw;
    max-height: 70vh;
    display: flex;
    flex-direction: column;
    box-shadow: var(--shadow);
  }

  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
  }

  .modal-header h2 {
    font-size: 18px;
    font-weight: 600;
    color: var(--text);
    margin: 0;
  }

  .close-btn {
    background: transparent;
    color: var(--text-dim);
    padding: 4px;
  }

  .close-btn:hover {
    color: var(--text);
  }

  .modal-body {
    overflow-y: auto;
    padding: 8px 0;
  }

  .loading, .empty {
    padding: 24px 20px;
    text-align: center;
    color: var(--text-muted);
  }

  .project-row {
    display: flex;
    align-items: center;
    padding: 12px 20px;
    cursor: pointer;
    transition: background 0.1s ease;
  }

  .project-row:hover {
    background: var(--bg-card-hover);
  }

  .project-info {
    flex: 1;
    min-width: 0;
  }

  .project-name {
    display: block;
    font-weight: 500;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .project-meta {
    font-size: 12px;
    color: var(--text-muted);
  }

  .delete-btn {
    background: transparent;
    color: var(--text-muted);
    padding: 6px;
    flex-shrink: 0;
  }

  .delete-btn:hover {
    color: var(--error);
  }
</style>
