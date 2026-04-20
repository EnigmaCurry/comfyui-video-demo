<script>
  import { Pencil, Check, X, RotateCcw } from 'lucide-svelte';
  import { updateNarration, regenerateNarration, setNarrationActiveIndex } from '../lib/api.js';

  let { transitions = $bindable([]), keyframes = [], projectId = '',
        onstatus, onreset } = $props();

  let activeIndex = $state(-1);
  let initialized = $state(false);
  let editing = $state({});
  let editTexts = $state({});

  // All narrations are "approved" once you've reviewed them — no rendering needed.
  // The active index tracks which one you're currently reviewing.
  $effect(() => {
    if (initialized || transitions.length === 0) return;
    initialized = true;
    activeIndex = 0;
  });

  let allReviewed = $derived(activeIndex >= transitions.length);

  function getKeyframe(id) {
    return keyframes.find(kf => kf.id === id);
  }

  function videoUrl(tr) {
    if (!tr?.video_filename || !projectId) return null;
    return `/api/projects/${projectId}/videos/${tr.video_filename}?v=${tr.seed || 0}`;
  }

  function startEdit(tr) {
    editTexts[tr.id] = tr.narration;
    editing[tr.id] = true;
  }

  async function saveEdit(tr) {
    try {
      await updateNarration(tr.id, editTexts[tr.id]);
      tr.narration = editTexts[tr.id];
      editing[tr.id] = false;
      onstatus({ detail: `Updated narration for transition ${tr.position + 1}` });
    } catch (e) {
      onstatus({ detail: `Update failed: ${e.message}` });
    }
  }

  function cancelEdit(tr) { editing[tr.id] = false; }

  function handleApprove() {
    const nextIndex = activeIndex + 1;
    if (nextIndex < transitions.length) {
      activeIndex = nextIndex;
      setNarrationActiveIndex(activeIndex);
      onstatus({ detail: `Approved narration #${activeIndex}. Reviewing #${nextIndex + 1}...` });
    } else {
      activeIndex = transitions.length;
      setNarrationActiveIndex(activeIndex);
      onstatus({ detail: 'All narration approved!' });
    }
  }

  async function handleRegenerate() {
    if (!confirm('Regenerate all narration text? Your edits will be lost.')) return;
    onstatus({ detail: 'Regenerating narration...' });
    try {
      const data = await regenerateNarration();
      if (onreset) onreset({ detail: data.project });
      onstatus({ detail: 'Narration regenerated.' });
      initialized = false;
    } catch (e) {
      onstatus({ detail: `Failed: ${e.message}` });
    }
  }

  function autoFocus(node) {
    node.focus();
    node.setSelectionRange(node.value.length, node.value.length);
  }

  function editKeydown(e, tr) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEdit(tr); }
    else if (e.key === 'Escape') { cancelEdit(tr); }
  }
</script>

{#if transitions.length > 0}
  <div class="toolbar">
    <button class="toolbar-btn" onclick={handleRegenerate}>
      <RotateCcw size={14} /> Regenerate All
    </button>
  </div>

  <div class="narrations">
    {#each transitions as tr, i (tr.id)}
      {@const isActive = i === activeIndex}
      {@const isEditing = editing[tr.id]}

      <div class="narration-card" class:active={isActive}>
        <div class="card-header">
          <span class="position">{i + 1}</span>
          <span class="label">Transition {tr.position + 1}</span>
          {#if i < activeIndex}
            <span class="status-badge done">reviewed</span>
          {:else if isActive}
            <span class="status-badge rendering">reviewing</span>
          {:else}
            <span class="status-badge pending">pending</span>
          {/if}
        </div>

        <div class="card-content">
          {#if videoUrl(tr)}
            <div class="video-thumb">
              <!-- svelte-ignore a11y_media_has_caption -->
              <video src={videoUrl(tr)} loop muted autoplay></video>
            </div>
          {/if}

          <div class="narration-body">
            <p class="scene-prompt">{tr.prompt}</p>

            {#if isEditing}
              <textarea
                bind:value={editTexts[tr.id]}
                onkeydown={(e) => editKeydown(e, tr)}
                rows="4"
                class="edit-textarea"
                use:autoFocus
              ></textarea>
              <div class="edit-actions">
                <button class="btn-save" onclick={() => saveEdit(tr)}><Check size={14} /> Save</button>
                <button class="btn-cancel" onclick={() => cancelEdit(tr)}><X size={14} /> Cancel</button>
              </div>
            {:else}
              <blockquote class="narration-text">
                {tr.narration || '(no narration)'}
              </blockquote>
            {/if}
          </div>
        </div>

        <div class="card-actions">
          <button class="btn-icon" onclick={() => startEdit(tr)} title="Edit narration">
            <Pencil size={16} />
          </button>
          {#if isActive && !isEditing}
            <button class="btn-approve" onclick={handleApprove} title="Approve narration">
              <Check size={16} /> Approve
            </button>
          {/if}
        </div>
      </div>
    {/each}
  </div>

  {#if allReviewed}
    <div class="all-done">
      <span>All narration approved!</span>
    </div>
  {/if}
{:else}
  <div class="empty">
    <p>No narration yet. Approve all transitions first.</p>
  </div>
{/if}

<style>
  .toolbar {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-bottom: 12px;
  }

  .toolbar-btn {
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border);
    font-size: 13px;
    padding: 6px 14px;
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }

  .toolbar-btn:hover:not(:disabled) {
    color: var(--text-dim);
    border-color: var(--text-muted);
  }

  .narrations {
    display: flex;
    flex-direction: column;
    gap: 16px;
    margin-bottom: 24px;
  }

  .narration-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }

  .narration-card.active {
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent);
  }

  .card-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
  }

  .position {
    font-weight: 700;
    font-size: 18px;
    color: var(--text);
    min-width: 24px;
  }

  .label { font-size: 13px; color: var(--text-muted); }

  .status-badge {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: 500;
    margin-left: auto;
  }

  .status-badge.pending { background: var(--accent-bg); color: var(--accent); }
  .status-badge.rendering { background: var(--accent-bg); color: var(--accent-hover); }
  .status-badge.done { background: rgba(34, 197, 94, 0.15); color: var(--success); }

  .card-content {
    display: flex;
    gap: 16px;
    padding: 14px;
  }

  .video-thumb {
    width: 200px;
    flex-shrink: 0;
    border-radius: var(--radius);
    overflow: hidden;
    background: #000;
  }

  .video-thumb video {
    width: 100%;
    display: block;
  }

  .narration-body {
    flex: 1;
    min-width: 0;
  }

  .scene-prompt {
    font-size: 12px;
    color: var(--text-muted);
    margin-bottom: 10px;
    line-height: 1.4;
    font-style: italic;
  }

  .narration-text {
    font-size: 15px;
    color: var(--text);
    line-height: 1.6;
    margin: 0;
    padding: 12px 16px;
    border-left: 3px solid var(--accent);
    background: var(--bg);
    border-radius: 0 var(--radius) var(--radius) 0;
  }

  .edit-textarea {
    width: 100%;
    resize: vertical;
    font-size: 15px;
    min-height: 80px;
    line-height: 1.6;
  }

  .edit-actions {
    display: flex;
    gap: 6px;
    margin-top: 8px;
  }

  .btn-save {
    background: var(--accent);
    color: white;
    font-size: 12px;
    padding: 4px 12px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .btn-cancel {
    background: transparent;
    color: var(--text-dim);
    border: 1px solid var(--border);
    font-size: 12px;
    padding: 4px 12px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .card-actions {
    display: flex;
    gap: 4px;
    padding: 8px 14px;
    border-top: 1px solid var(--border);
    align-items: center;
  }

  .btn-icon {
    background: transparent;
    color: var(--text-dim);
    padding: 6px 10px;
    font-size: 16px;
    border-radius: var(--radius);
  }

  .btn-icon:hover:not(:disabled) {
    background: var(--bg-card-hover);
    color: var(--text);
  }

  .btn-approve {
    background: var(--success);
    color: white;
    font-size: 13px;
    font-weight: 500;
    padding: 6px 14px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-left: auto;
  }

  .btn-approve:hover { filter: brightness(1.1); }

  .all-done {
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 20px 24px;
    margin-bottom: 24px;
  }

  .all-done span {
    font-size: 16px;
    font-weight: 500;
    color: var(--success);
  }

  .empty {
    text-align: center;
    padding: 80px 20px;
    color: var(--text-muted);
    border: 2px dashed var(--border);
    border-radius: var(--radius-lg);
    margin-bottom: 24px;
  }
</style>
