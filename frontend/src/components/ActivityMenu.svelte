<script>
  import { Menu, Check } from 'lucide-svelte';
  import { ACTIVITIES } from '../lib/api.js';

  let { activity = $bindable('film-director'), onchange } = $props();

  let open = $state(false);

  function select(id) {
    if (id !== activity) {
      activity = id;
      onchange?.({ detail: id });
    }
    open = false;
  }

  function handleKeydown(e) {
    if (e.key === 'Escape') open = false;
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="activity-menu">
  <button class="menu-btn" onclick={() => open = !open} title="Switch activity">
    <Menu size={18} />
  </button>

  {#if open}
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div class="backdrop" onclick={() => open = false}></div>
    <div class="dropdown">
      {#each ACTIVITIES as act}
        <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
        <div class="menu-item" class:active={activity === act.id}
             onclick={() => select(act.id)}>
          <div class="item-text">
            <span class="item-label">{act.label}</span>
            <span class="item-sub">{act.subtitle}</span>
          </div>
          {#if activity === act.id}
            <Check size={16} />
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .activity-menu {
    position: relative;
  }

  .menu-btn {
    background: transparent;
    color: var(--text-dim);
    border: 1px solid var(--border);
    padding: 6px 8px;
    display: flex;
    align-items: center;
  }

  .menu-btn:hover {
    color: var(--text);
    border-color: var(--text-muted);
  }

  .backdrop {
    position: fixed;
    inset: 0;
    z-index: 999;
  }

  .dropdown {
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    min-width: 280px;
    z-index: 1000;
    box-shadow: var(--shadow);
    padding: 6px 0;
  }

  .menu-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 16px;
    cursor: pointer;
    color: var(--text-dim);
    transition: background 0.1s ease;
  }

  .menu-item:hover {
    background: var(--bg-card-hover);
  }

  .menu-item.active {
    color: var(--text);
  }

  .item-text {
    flex: 1;
    min-width: 0;
  }

  .item-label {
    display: block;
    font-weight: 500;
    font-size: 14px;
    color: inherit;
  }

  .item-sub {
    display: block;
    font-size: 12px;
    color: var(--text-muted);
  }
</style>
