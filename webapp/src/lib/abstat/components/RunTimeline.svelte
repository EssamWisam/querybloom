<script>
  export let events = [];
  export let running = false;

  const EMPTY_PROPERTIES_DETAIL =
    "The property-discovery SPARQL query returned 0 usable rows.";

  function eventTitle(item) {
    return item?.event || item?.type || "event";
  }

  function eventMeta(item) {
    return [
      item?.stage,
      item?.timestamp ? new Date(item.timestamp).toLocaleTimeString() : null,
    ]
      .filter(Boolean)
      .join(" · ");
  }

  function eventMessage(item) {
    return (item?.message || "")
      .replace(EMPTY_PROPERTIES_DETAIL, "")
      .replace(/\s+\./g, ".")
      .trim();
  }

  function hasDetails(item) {
    const payload = item?.payload;
    return (
      payload &&
      typeof payload === "object" &&
      Object.keys(payload).length > 0 &&
      (item.event === "error" ||
        item.event === "warning" ||
        payload.query ||
        payload.result ||
        payload.hint)
    );
  }

  function formatDetails(payload) {
    return JSON.stringify(payload, null, 2);
  }
</script>

<section class="timeline">
  <header>
    <div>
      <h2>Live run</h2>
      <p>
        {running
          ? "Streaming from backend"
          : events.length
            ? "Run stream complete"
            : "No active stream"}
      </p>
    </div>
    <span class:live={running}>{running ? "Live" : "Idle"}</span>
  </header>

  <div class="items">
    {#if !events.length}
      <p class="empty">
        Start a sampling run to watch property discovery, graph formation, and
        subgraph grouping here.
      </p>
    {/if}
    {#each events as item, index (item.id || index)}
      <article
        class="event"
        class:error={item.event === "error"}
        class:important={item.event === "subgraph.discovered" ||
          item.event === "subgraph.samples" ||
          item.event === "graph.updated"}
      >
        <div class="dot"></div>
        <div>
          <h3>{eventTitle(item)}</h3>
          {#if eventMeta(item)}<p class="meta">{eventMeta(item)}</p>{/if}
          {#if eventMessage(item)}<p>{eventMessage(item)}</p>{/if}
          {#if hasDetails(item)}
            <details>
              <summary>Learn more</summary>
              <pre>{formatDetails(item.payload)}</pre>
            </details>
          {/if}
        </div>
      </article>
    {/each}
  </div>
</section>

<style>
  .timeline {
    height: 100%;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 16px;
    border-bottom: 1px solid var(--border-default);
  }

  h2,
  h3,
  p {
    margin: 0;
  }

  h2 {
    color: var(--color-uni-dark-blue);
    font-size: 1rem;
  }

  header p,
  .meta,
  .empty {
    color: #66708a;
    font-size: 0.82rem;
  }

  header span {
    border: 1px solid #d7ddeb;
    border-radius: 999px;
    padding: 3px 9px;
    color: #65708c;
    font-size: 0.74rem;
    font-weight: 800;
  }

  header span.live {
    border-color: rgba(0, 160, 130, 0.38);
    color: #087a65;
    background: rgba(0, 160, 130, 0.08);
  }

  .items {
    overflow: auto;
    padding: 14px 16px 22px;
  }

  .event {
    display: grid;
    grid-template-columns: 14px 1fr;
    gap: 10px;
    padding: 10px 0;
    border-bottom: 1px solid #edf0f6;
  }

  .event h3 {
    color: #202842;
    font-size: 0.9rem;
  }

  .event p:not(.meta) {
    color: #4f5873;
    font-size: 0.84rem;
  }

  details {
    margin-top: 7px;
  }

  summary {
    width: fit-content;
    color: #2e3d72;
    cursor: pointer;
    font-size: 0.78rem;
    font-weight: 800;
  }

  pre {
    max-height: 260px;
    overflow: auto;
    margin: 8px 0 0;
    border: 1px solid #e3e8f5;
    border-radius: 6px;
    background: #f8faff;
    padding: 9px;
    color: #24304d;
    font-size: 0.76rem;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .dot {
    width: 9px;
    height: 9px;
    margin-top: 5px;
    border-radius: 50%;
    background: #adb9d8;
  }

  .important .dot {
    background: var(--color-uni-green);
  }

  .error .dot {
    background: #c2410c;
  }

  .error h3,
  .error p:not(.meta) {
    color: #9a3412;
  }

  .empty {
    padding: 16px 0;
  }
</style>
