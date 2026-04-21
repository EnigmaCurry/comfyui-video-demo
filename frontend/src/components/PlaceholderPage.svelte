<script>
  let { title, description } = $props();
</script>

<div class="placeholder">
  <h2>{title}</h2>
  <p>{description}</p>
</div>

<style>
  .placeholder {
    text-align: center;
    padding: 80px 20px;
    color: var(--text-muted);
    border: 2px dashed var(--border);
    border-radius: var(--radius-lg);
  }

  h2 {
    font-size: 20px;
    font-weight: 600;
    color: var(--text-dim);
    margin-bottom: 8px;
  }

  p {
    font-size: 15px;
  }
</style>
