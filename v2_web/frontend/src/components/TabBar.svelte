<script>
  let { tabs, active = $bindable(''), projectLoaded = false } = $props();
</script>

<nav class="tab-bar">
  {#each tabs as tab}
    <button
      class="tab"
      class:active={active === tab.id}
      class:disabled={tab.id !== 'premise' && !projectLoaded}
      disabled={tab.id !== 'premise' && !projectLoaded}
      onclick={() => active = tab.id}
    >
      {tab.label}
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

  .tab.disabled {
    opacity: 0.35;
  }
</style>
