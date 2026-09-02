<script>
  /** @type {any} */
  export let data = null;
  export let depth = 0;

  let activeTab = "visual"; // "visual" | "json"
  let copied = false;
  let copyTimeout = null;

  function formatKey(key) {
    if (!key) return "";
    return key
      .replace(/_/g, " ")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }

  function isPrimitiveArray(arr) {
    return (
      Array.isArray(arr) &&
      arr.every(
        (item) =>
          typeof item === "string" ||
          typeof item === "number" ||
          typeof item === "boolean" ||
          item == null,
      )
    );
  }

  function isCodeString(val, key = "") {
    if (typeof val !== "string") return false;
    const lowerKey = String(key).toLowerCase();
    if (
      lowerKey.includes("sparql") ||
      lowerKey.includes("query") ||
      lowerKey.includes("sql")
    )
      return true;
    if (
      val.includes("\n") &&
      (val.includes("SELECT ") ||
        val.includes("WHERE {") ||
        val.includes("PREFIX "))
    )
      return true;
    return false;
  }

  function copyJson() {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      copied = true;
      if (copyTimeout) clearTimeout(copyTimeout);
      copyTimeout = setTimeout(() => {
        copied = false;
      }, 2000);
    }
  }
</script>

{#if depth === 0}
  <div class="viewer-container">
    <div class="viewer-toolbar">
      <div class="view-tabs">
        <button
          type="button"
          class="view-tab"
          class:active={activeTab === "visual"}
          on:click={() => (activeTab = "visual")}
        >
          Visual View
        </button>
        <button
          type="button"
          class="view-tab"
          class:active={activeTab === "json"}
          on:click={() => (activeTab = "json")}
        >
          Raw JSON
        </button>
      </div>

      <button type="button" class="copy-json-btn" on:click={copyJson}>
        {copied ? "✓ Copied" : "Copy JSON"}
      </button>
    </div>

    {#if activeTab === "json"}
      <pre class="json-code"><code>{JSON.stringify(data, null, 2)}</code></pre>
    {:else}
      <div class="visual-body">
        <svelte:self {data} depth={depth + 1} />
      </div>
    {/if}
  </div>
{:else}
  {#if data == null}
    <span class="val-null">—</span>
  {:else if typeof data === "boolean"}
    <span class="val-badge" class:badge-true={data} class:badge-false={!data}>
      {data ? "✓ True" : "✗ False"}
    </span>
  {:else if typeof data === "number"}
    <span class="val-number">{data.toLocaleString()}</span>
  {:else if typeof data === "string"}
    <p class="val-string">{data || "—"}</p>
  {:else if Array.isArray(data)}
    {#if data.length === 0}
      <span class="val-empty">None / Empty list</span>
    {:else if isPrimitiveArray(data)}
      <div class="pill-list">
        {#each data as item}
          <span class="tag-pill">{item}</span>
        {/each}
      </div>
    {:else}
      <div class="array-card-list">
        {#each data as item, i}
          <div class="array-card">
            <div class="array-card-index">Item {i + 1}</div>
            <div class="array-card-content">
              <svelte:self data={item} depth={depth + 1} />
            </div>
          </div>
        {/each}
      </div>
    {/if}
  {:else if typeof data === "object"}
    {@const entries = Object.entries(data)}
    {#if entries.length === 0}
      <span class="val-empty">Empty object</span>
    {:else}
      <div class="kv-grid">
        {#each entries as [key, val]}
          <div class="kv-row">
            <span class="kv-key">{formatKey(key)}</span>
            <div class="kv-val">
              {#if val == null}
                <span class="val-null">—</span>
              {:else if typeof val === "boolean"}
                <span
                  class="val-badge"
                  class:badge-true={val}
                  class:badge-false={!val}
                >
                  {val ? "✓ Yes" : "✗ No"}
                </span>
              {:else if typeof val === "number"}
                <span class="val-number">{val.toLocaleString()}</span>
              {:else if typeof val === "string"}
                {#if isCodeString(val, key)}
                  <pre class="val-code"><code>{val}</code></pre>
                {:else}
                  <p class="val-string">{val || "—"}</p>
                {/if}
              {:else if isPrimitiveArray(val)}
                {#if val.length === 0}
                  <span class="val-empty">None</span>
                {:else}
                  <div class="pill-list">
                    {#each val as item}
                      <span class="tag-pill">{item}</span>
                    {/each}
                  </div>
                {/if}
              {:else}
                <div class="nested-block">
                  <svelte:self data={val} depth={depth + 1} />
                </div>
              {/if}
            </div>
          </div>
        {/each}
      </div>
    {/if}
  {:else}
    <span>{String(data)}</span>
  {/if}
{/if}

<style>
  .viewer-container {
    display: grid;
    gap: 12px;
    width: 100%;
  }

  .viewer-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #e2e8f0;
    padding-bottom: 10px;
  }

  .view-tabs {
    display: flex;
    gap: 4px;
    background: #f1f5f9;
    padding: 3px;
    border-radius: 6px;
  }

  .view-tab {
    border: none;
    background: transparent;
    padding: 4px 12px;
    font-size: 0.78rem;
    font-weight: 600;
    color: #64748b;
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .view-tab.active {
    background: #ffffff;
    color: #1e293b;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  }

  .copy-json-btn {
    padding: 4px 10px;
    font-size: 0.75rem;
    font-weight: 600;
    color: #475569;
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .copy-json-btn:hover {
    background: #f1f5f9;
    color: #0f172a;
  }

  .json-code {
    margin: 0;
    background: #0f172a;
    color: #f8fafc;
    padding: 14px;
    border-radius: 8px;
    font-size: 0.8rem;
    overflow: auto;
    max-height: 380px;
    line-height: 1.45;
  }

  .visual-body {
    display: grid;
    gap: 12px;
  }

  .kv-grid {
    display: grid;
    gap: 10px;
    background: #ffffff;
  }

  .kv-row {
    display: grid;
    grid-template-columns: 160px 1fr;
    gap: 14px;
    padding: 10px 12px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    align-items: flex-start;
  }

  .kv-key {
    font-size: 0.76rem;
    font-weight: 700;
    text-transform: uppercase;
    color: #64748b;
    letter-spacing: 0.03em;
    padding-top: 2px;
  }

  .kv-val {
    min-width: 0;
  }

  .val-null,
  .val-empty {
    color: #94a3b8;
    font-size: 0.82rem;
    font-style: italic;
  }

  .val-badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 5px;
    font-size: 0.75rem;
    font-weight: 600;
  }

  .badge-true {
    background: #dcfce7;
    color: #15803d;
    border: 1px solid #bbf7d0;
  }

  .badge-false {
    background: #f1f5f9;
    color: #64748b;
    border: 1px solid #e2e8f0;
  }

  .val-number {
    font-weight: 600;
    color: #0f172a;
    font-size: 0.85rem;
  }

  .val-string {
    margin: 0;
    color: #1e293b;
    font-size: 0.86rem;
    line-height: 1.45;
    word-break: break-word;
  }

  .val-code {
    margin: 0;
    background: #f1f5f9;
    color: #0f172a;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 0.78rem;
    overflow-x: auto;
    white-space: pre;
  }

  .pill-list {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .tag-pill {
    background: #e0e7ff;
    color: #3730a3;
    border: 1px solid #c7d2fe;
    border-radius: 4px;
    padding: 2px 7px;
    font-size: 0.74rem;
    font-weight: 600;
  }

  .array-card-list {
    display: grid;
    gap: 8px;
    width: 100%;
  }

  .array-card {
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    background: #ffffff;
    overflow: hidden;
  }

  .array-card-index {
    background: #f1f5f9;
    padding: 4px 10px;
    font-size: 0.72rem;
    font-weight: 700;
    color: #64748b;
    text-transform: uppercase;
    border-bottom: 1px solid #e2e8f0;
  }

  .array-card-content {
    padding: 10px;
  }

  .nested-block {
    border-left: 2px solid #cbd5e1;
    padding-left: 10px;
  }
</style>
