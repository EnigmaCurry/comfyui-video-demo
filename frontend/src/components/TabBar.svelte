<script>
  import { Lock } from 'lucide-svelte';

  // tabs: [{ id, label }]
  // enabledThrough: the furthest tab id that is reachable
  let { tabs, active = $bindable(''), enabledThrough = 'premise' } = $props();

  const tabIndex = (id) => tabs.findIndex(t => t.id === id);
  const enabledIndex = $derived(tabIndex(enabledThrough));

  function isEnabled(id) {
    return tabIndex(id) <= enabledIndex;
  }

  function isLocked(id) {
    // A tab is "locked" (greyed out content) if it's before the current frontier
    return tabIndex(id) < enabledIndex;
  }
</script>

<nav class="tab-bar">
  {#each tabs as tab}
    <button
      class="tab"
      class:active={active === tab.id}
      class:locked={isLocked(tab.id) && active !== tab.id}
      disabled={!isEnabled(tab.id)}
      onclick={() => active = tab.id}
    >
      {tab.label}
      {#if isLocked(tab.id)}
        <Lock size={11} />
      {/if}
    </button>
  {/each}
</nav>

<style>
  .tab-bar {
    display: flex;
    gap: 2px;
    border-bottom: 2px solid var(--border);
    margin-bottom: 24px;
  }

  .tab {
    background: transparent;
    color: var(--text-muted);
    font-size: 14px;
    font-weight: 500;
    padding: 10px 20px;
    border-radius: var(--radius) var(--radius) 0 0;
    position: relative;
    transition: all 0.15s ease;
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }

  .tab:hover:not(:disabled) {
    color: var(--text-dim);
    background: var(--bg-card);
  }

  .tab.active {
    color: var(--text);
    background: var(--bg-card);
  }

  .tab.active::after {
    content: '';
    position: absolute;
    bottom: -2px;
    left: 0;
    right: 0;
    height: 2px;
    background: var(--accent);
  }

  .tab.locked {
    color: var(--text-muted);
    opacity: 0.6;
  }

  .tab:disabled {
    opacity: 0.25;
    cursor: not-allowed;
  }
</style>
