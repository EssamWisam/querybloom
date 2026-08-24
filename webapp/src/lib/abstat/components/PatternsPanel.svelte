<script>
  import AbstatGraph from "./AbstatGraph.svelte";
  import { shortName } from "../graph.js";

  export let graph = null;
  export let properties = [];
  export let summary = {};
  export let running = false;
  export let discoveryPhase = false;
  export let skipDiscoveryPending = false;
  export let onSkipDiscovery = null;

  $: completed = properties.filter((item) => item.status === "completed");
  $: graphRelevant = completed.filter(
    (item) => (item.added_object_patterns || 0) > 0,
  );
  $: totalObjectPatterns = completed.reduce(
    (maxCount, item) => Math.max(maxCount, item.total_object_patterns || 0),
    0,
  );
  $: totalAttributePatterns = completed.reduce(
    (maxCount, item) => Math.max(maxCount, item.total_attribute_patterns || 0),
    0,
  );
  $: topProperties = [...graphRelevant]
    .sort(
      (left, right) =>
        (right.added_object_patterns || 0) +
        (right.added_attribute_patterns || 0) -
        ((left.added_object_patterns || 0) +
          (left.added_attribute_patterns || 0)),
    )
    .slice(0, 12);

  function displayName(item) {
    return item.label || item.short_name || shortName(item.uri) || "Property";
  }

  let selectedNode = null;

  function handleNodeClick(nodeData) {
    selectedNode = nodeData;
  }
</script>

<section class="patterns-workspace">
  <div class="graph-region">
    {#if graph}
      <AbstatGraph
        {graph}
        subgraphs={[]}
        selectedIndex={null}
        preferGridLayout={true}
        useCyanNodeFocus={true}
        onNodeClick={handleNodeClick}
      />
    {:else}
      <div class="graph-empty">
        Pattern graph will render as soon as `graph.updated` arrives.
      </div>
    {/if}
  </div>

  <aside class="inspector">
    <header>
      <p class="eyebrow">Pattern graph</p>
      <h2>Patterns</h2>
      {#if summary.patternCache?.loaded}
        <p class="cache-note">Loaded from cache</p>
      {/if}
    </header>

    <dl>
      <div>
        <dt>Properties done</dt>
        <dd>{completed.length}</dd>
      </div>
      <div>
        <dt>Graph updates</dt>
        <dd>{graphRelevant.length}</dd>
      </div>
      <div>
        <dt>Object patterns</dt>
        <dd>{totalObjectPatterns}</dd>
      </div>
      <div>
        <dt>Attribute patterns</dt>
        <dd>{totalAttributePatterns}</dd>
      </div>
    </dl>

    {#if running && discoveryPhase && onSkipDiscovery}
      <button
        class="skip-btn"
        type="button"
        disabled={skipDiscoveryPending}
        on:click={onSkipDiscovery}
        >{#if skipDiscoveryPending}<span class="skip-spinner" aria-hidden="true"
          ></span>{/if}{skipDiscoveryPending
          ? "Skipping to subgraphs..."
          : "Skip to subgraphs →"}</button
      >
    {/if}

    {#if selectedNode}
      <section class="node-inspector">
        <h3>Selected class</h3>
        <div class="node-card">
          <span class="node-label">{selectedNode.label}</span>
          <a
            class="node-uri"
            href={selectedNode.uri}
            target="_blank"
            rel="noopener noreferrer"
            title={selectedNode.uri}>{selectedNode.uri}</a
          >
        </div>
        {#if selectedNode.outEdges.length}
          <h4>Outgoing ({selectedNode.outEdges.length})</h4>
          <ul class="edge-list">
            {#each selectedNode.outEdges as e}
              <li>
                <span class="pred">{e.predicate}</span> →
                <span class="nbr">{e.neighbor}</span>{#if e.support != null}
                  <span class="sup">×{e.support}</span>{/if}
              </li>
            {/each}
          </ul>
        {/if}
        {#if selectedNode.inEdges.length}
          <h4>Incoming ({selectedNode.inEdges.length})</h4>
          <ul class="edge-list">
            {#each selectedNode.inEdges as e}
              <li>
                <span class="nbr">{e.neighbor}</span> →
                <span class="pred">{e.predicate}</span>{#if e.support != null}
                  <span class="sup">×{e.support}</span>{/if}
              </li>
            {/each}
          </ul>
        {/if}
        {#if !selectedNode.outEdges.length && !selectedNode.inEdges.length}
          <p class="empty">No edges in current graph view.</p>
        {/if}
      </section>
    {/if}

    <section class="leaders">
      <h3>Most productive properties</h3>
      {#if !topProperties.length}
        <p class="empty">
          Graph-relevant property summaries will appear here once object
          patterns are added.
        </p>
      {/if}
      {#each topProperties as item}
        <article>
          <strong>{displayName(item)}</strong>
          <small
            >+{item.added_object_patterns || 0} object · +{item.added_attribute_patterns ||
              0} attribute</small
          >
        </article>
      {/each}
    </section>
  </aside>
</section>

<style>
  .patterns-workspace {
    height: 100%;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 320px;
    grid-template-rows: minmax(0, 1fr);
    min-height: 0;
    overflow: hidden;
  }

  .graph-region {
    min-width: 0;
    min-height: 0;
    height: 100%;
    display: grid;
    overflow: hidden;
    background: #fbfcff;
  }

  .graph-empty {
    display: grid;
    place-items: center;
    height: 100%;
    color: #66708a;
  }

  .inspector {
    min-height: 0;
    overflow: auto;
    border-left: 1px solid var(--border-default);
    background: #fff;
    padding: 16px;
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

  h3 {
    color: #202842;
    font-size: 0.92rem;
    margin-bottom: 10px;
  }

  .eyebrow,
  .cache-note,
  .empty,
  dt,
  small {
    color: #66708a;
    font-size: 0.8rem;
  }

  .cache-note {
    color: var(--color-uni-green);
    font-weight: 700;
  }

  .eyebrow {
    color: var(--color-uni-green);
    font-size: 0.72rem;
    font-weight: 800;
    text-transform: uppercase;
  }

  dl {
    display: grid;
    gap: 8px;
    margin: 14px 0 18px;
  }

  dl div {
    border: 1px solid #e4e8f4;
    border-radius: 7px;
    padding: 8px;
  }

  dt {
    font-weight: 800;
    text-transform: uppercase;
  }

  dd {
    margin: 2px 0 0;
    color: #171f3b;
    font-weight: 800;
  }

  .leaders {
    display: grid;
    gap: 10px;
  }

  .skip-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 100%;
    margin-bottom: 18px;
    padding: 9px 14px;
    background: var(--color-uni-dark-blue, #1f2947);
    color: #fff;
    border: none;
    border-radius: 7px;
    font-size: 0.85rem;
    font-weight: 700;
    cursor: pointer;
    transition: opacity 0.15s;
  }

  .skip-btn:disabled {
    cursor: wait;
    opacity: 0.9;
  }

  .skip-spinner {
    width: 12px;
    height: 12px;
    border: 2px solid rgba(255, 255, 255, 0.35);
    border-top-color: #fff;
    border-radius: 50%;
    flex-shrink: 0;
    animation: skip-spin 0.7s linear infinite;
  }

  .skip-btn:hover {
    opacity: 0.85;
  }

  @keyframes skip-spin {
    to {
      transform: rotate(360deg);
    }
  }

  .leaders article {
    border: 1px solid #edf0f6;
    border-radius: 7px;
    padding: 9px;
    display: grid;
    gap: 4px;
  }

  .leaders strong {
    color: #1f2947;
  }

  .node-inspector {
    margin-bottom: 18px;
    border: 1px solid rgba(99, 179, 237, 0.35);
    border-radius: 9px;
    padding: 12px;
    background: rgba(99, 179, 237, 0.05);
  }

  .node-inspector h3 {
    color: #2b6cb0;
    margin-bottom: 8px;
  }

  .node-inspector h4 {
    font-size: 0.78rem;
    font-weight: 800;
    text-transform: uppercase;
    color: #66708a;
    margin: 10px 0 5px;
  }

  .node-card {
    display: grid;
    gap: 2px;
    margin-bottom: 4px;
  }

  .node-label {
    font-weight: 700;
    color: #1f2947;
    font-size: 0.95rem;
  }

  .node-uri {
    font-size: 0.72rem;
    color: #63b3ed;
    word-break: break-all;
    text-decoration: none;
    opacity: 0.8;
  }

  .node-uri:hover {
    opacity: 1;
    text-decoration: underline;
  }

  .edge-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: 4px;
  }

  .edge-list li {
    font-size: 0.8rem;
    color: #2a3450;
    background: #fff;
    border: 1px solid #e4e8f4;
    border-radius: 5px;
    padding: 4px 7px;
    display: flex;
    flex-wrap: wrap;
    gap: 3px;
    align-items: center;
  }

  .pred {
    color: #2b6cb0;
    font-weight: 700;
  }

  .nbr {
    color: #1f2947;
    font-weight: 600;
  }

  .sup {
    color: #66708a;
    font-size: 0.73rem;
    margin-left: auto;
  }

  @media (max-width: 1100px) {
    .patterns-workspace {
      grid-template-columns: 1fr;
    }

    .inspector {
      border-left: 0;
      border-top: 1px solid var(--border-default);
    }
  }
</style>
