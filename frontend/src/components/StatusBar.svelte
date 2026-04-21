<script>
  let { message = '' } = $props();
</script>

{#if message}
  <div class="status-bar">
    <span class="dot"></span>
    <span>{message}</span>
  </div>
{/if}

<style>
  .status-bar {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    background: var(--bg-card);
    border-top: 1px solid var(--border);
    padding: 10px 24px;
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--text-dim);
    z-index: 100;
  }

  .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--accent);
    flex-shrink: 0;
  }
</style>
