<script>
  import { Sparkles, ArrowDown, Lock } from 'lucide-svelte';
  import { suggestPremise, setPremise } from '../lib/api.js';

  let { onstatus, onpremise, locked = false, activity = 'film-director' } = $props();

  let notes = $state('');
  let premise = $state('');
  let suggesting = $state(false);
  let setting = $state(false);

  export function setPremiseText(text) {
    premise = text;
  }

  export function setNotesText(text) {
    notes = text;
  }

  async function handleSuggest() {
    if (!notes.trim()) return;
    suggesting = true;
    onstatus({ detail: 'Generating premise from your notes...' });
    try {
      const data = await suggestPremise(notes.trim());
      premise = data.premise;
      onstatus({ detail: 'Premise suggested. Edit it or proceed to Story.' });
    } catch (e) {
      onstatus({ detail: `Suggestion failed: ${e.message}` });
    } finally {
      suggesting = false;
    }
  }

  async function handleSetPremise() {
    if (!premise.trim()) return;
    setting = true;
    onstatus({ detail: 'Creating project...' });
    try {
      const data = await setPremise(premise.trim(), activity);
      onpremise({ detail: data.project });
      onstatus({ detail: `Project "${data.project.name}" created. Proceed to Story.` });
    } catch (e) {
      onstatus({ detail: `Failed: ${e.message}` });
    } finally {
      setting = false;
    }
  }
</script>

<div class="premise-page" class:locked>
  {#if locked}
    <div class="locked-banner">
      <Lock size={14} /> Premise is locked. Go to the Story tab to continue.
    </div>
  {/if}

  <div class="section">
    <h2>Notes</h2>
    <p class="hint">
      Stream of consciousness. Nouns, ideas, moods, images — anything that inspires you.
    </p>
    <textarea
      placeholder="lighthouse, isolation, storm, mysterious door, old photographs, whispering sea, rust, forgotten letters..."
      bind:value={notes}
      disabled={locked || suggesting}
      class="notes-input"
      rows="4"
    ></textarea>
    <button
      class="suggest-btn"
      onclick={handleSuggest}
      disabled={locked || suggesting || !notes.trim()}
    >
      <Sparkles size={16} />
      {suggesting ? 'Suggesting...' : 'Suggest Premise'}
    </button>
  </div>

  <div class="divider">
    <ArrowDown size={16} />
  </div>

  <div class="section">
    <h2>Premise</h2>
    <p class="hint">
      The foundation of your film. Write it yourself or generate it from your notes above.
    </p>
    <textarea
      placeholder="A lighthouse keeper on a remote island discovers a locked door in the basement that wasn't there yesterday. Outside, a storm is building, and the radio has gone silent."
      bind:value={premise}
      disabled={locked || setting}
      class="premise-input"
      rows="4"
    ></textarea>
    {#if !locked}
      <button
        class="proceed-btn"
        onclick={handleSetPremise}
        disabled={setting || !premise.trim()}
      >
        {setting ? 'Creating...' : 'Establish Premise'}
      </button>
    {/if}
  </div>
</div>

<style>
  .premise-page {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 28px;
  }

  .premise-page.locked {
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

  .section {
    margin-bottom: 8px;
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

  .notes-input, .premise-input {
    width: 100%;
    resize: vertical;
    line-height: 1.6;
    font-size: 15px;
    margin-bottom: 12px;
  }

  .suggest-btn {
    background: var(--bg-card-hover);
    color: var(--text-dim);
    border: 1px solid var(--border);
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 14px;
    padding: 8px 18px;
  }

  .suggest-btn:hover:not(:disabled) {
    color: var(--text);
    border-color: var(--text-muted);
  }

  .divider {
    display: flex;
    justify-content: center;
    padding: 16px 0;
    color: var(--text-muted);
  }

  .proceed-btn {
    background: var(--accent);
    color: white;
    font-weight: 500;
    padding: 10px 28px;
    font-size: 15px;
    float: right;
  }

  .proceed-btn:hover:not(:disabled) {
    background: var(--accent-hover);
  }
</style>
