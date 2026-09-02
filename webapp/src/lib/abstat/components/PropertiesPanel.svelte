<script>
  import { shortName } from "../graph.js";

  export let properties = [];
  export let summary = {};
  export let running = false;

  $: completedCount = properties.filter(
    (item) => item.status === "completed",
  ).length;
  $: processingCount = properties.filter(
    (item) => item.status === "processing",
  ).length;

  function displayName(item) {
    return item.label || item.short_name || shortName(item.uri) || "Property";
  }

  function primaryMeta(item) {
    if (item.count != null) return `frequency ${item.count}`;
    if (item.num_new_types != null) return `${item.num_new_types} types`;
    if (summary.frequencyFetched === false) return "frequency not fetched";
    return "Awaiting details";
  }
</script>

<section class="properties-panel">
  <header>
    <div>
      <h2>Properties</h2>
      <p>Property discovery and per-property pattern extraction.</p>
      {#if summary.propertyCache?.loaded || summary.patternCache?.loaded}
        <p class="cache-note">
          {#if summary.patternCache?.loaded}
            Pattern summaries restored from cache.
          {:else}
            Property list restored from cache.
          {/if}
        </p>
      {/if}
    </div>
    <div class="stats">
      <article>
        <strong>{summary.listedCount || 0}</strong><span>Listed</span>
      </article>
      <article>
        <strong>{summary.filteredCount || 0}</strong><span>Ready</span>
      </article>
      <article><strong>{processingCount}</strong><span>Active</span></article>
      <article><strong>{completedCount}</strong><span>Done</span></article>
    </div>
  </header>

  <div class="rows">
    {#if !properties.length}
      <p class="empty">
        Property events will appear here as preprocessing starts.
      </p>
    {/if}

    {#each properties as item, idx (item.uri || `prop-${idx}`)}
      <article
        class:processing={item.status === "processing"}
        class:completed={item.status === "completed"}
      >
        <div class="row-head">
          <strong>{displayName(item)}</strong>
          <span>{item.status || (running ? "queued" : "idle")}</span>
        </div>
        {#if item.uri}<code>{item.uri}</code>{/if}
        <div class="meta">
          <small>{primaryMeta(item)}</small>
          <small
            >{item.added_object_patterns != null
              ? `+${item.added_object_patterns} object patterns`
              : ""}</small
          >
          <small
            >{item.added_attribute_patterns != null
              ? `+${item.added_attribute_patterns} attribute patterns`
              : ""}</small
          >
        </div>
      </article>
    {/each}
  </div>
</section>

<style>
  .properties-panel {
    height: 100%;
    display: grid;
    grid-template-rows: auto 1fr;
    min-height: 0;
    background: #fff;
  }

  header {
    display: grid;
    gap: 14px;
    padding: 16px;
    border-bottom: 1px solid var(--border-default);
  }

  h2,
  p {
    margin: 0;
  }

  h2 {
    color: var(--color-uni-dark-blue);
    font-size: 1rem;
  }

  p,
  .empty,
  .cache-note,
  code,
  small,
  span {
    color: #66708a;
    font-size: 0.82rem;
  }

  .cache-note {
    color: var(--color-uni-green);
    font-weight: 700;
    margin-top: 6px;
  }

  .stats {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 8px;
  }

  .stats article {
    border: 1px solid #e4e8f4;
    border-radius: 7px;
    padding: 9px;
    display: grid;
    gap: 2px;
  }

  .stats strong {
    color: #1a2444;
    font-size: 1rem;
  }

  .rows {
    overflow: auto;
    padding: 14px 16px 22px;
    display: grid;
    gap: 10px;
  }

  .rows article {
    border: 1px solid #e4e8f4;
    border-radius: 8px;
    padding: 10px;
    display: grid;
    gap: 7px;
  }

  .rows article.processing {
    border-color: rgba(0, 160, 130, 0.45);
    background: rgba(0, 160, 130, 0.06);
  }

  .rows article.completed {
    border-color: rgba(52, 74, 154, 0.25);
  }

  .row-head,
  .meta {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    flex-wrap: wrap;
  }

  .row-head strong {
    color: #1f2947;
  }

  code {
    overflow-wrap: anywhere;
  }

  @media (max-width: 920px) {
    .stats {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
</style>
