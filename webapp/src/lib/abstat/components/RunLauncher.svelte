<script>
  import FieldHelp from "./FieldHelp.svelte";
  import endpointCatalog from "$endpoints";

  /** @type {any} */
  export let defaults = null;
  /** @type {(payload: { title: string, config: Record<string, any> }) => void} */
  export let onStart = (_payload) => {};

  function endpointUrl(endpointIdOrUrl) {
    const endpoint = endpointCatalog[endpointIdOrUrl];
    if (typeof endpoint === "string") return endpoint;
    if (endpoint && typeof endpoint === "object")
      return endpoint.url || endpointIdOrUrl;
    return endpointIdOrUrl;
  }

  $: samplingUi = defaults?.ui?.sampling ?? {};
  $: samplingFields = samplingUi.fields ?? {};
  $: presets = samplingUi.presets ?? {};
  $: presetsLoaded = Object.keys(presets).length > 0;
  $: defaultsError = presetsLoaded
    ? ""
    : "Could not load sampling presets from the backend. Check that the API is running and refresh.";

  function fieldLabel(key, fallback) {
    return samplingFields[key]?.label ?? fallback;
  }

  function fieldDescription(key, fallback) {
    return samplingFields[key]?.description ?? fallback;
  }

  function clonePresetValue(value) {
    if (Array.isArray(value)) return [...value];
    if (value && typeof value === "object") return { ...value };
    return value;
  }

  function applyPreset(presetId) {
    const preset = presets[presetId] || presets.custom;
    if (!preset) return;
    const config = preset.config || {};
    const preprocess = config.preprocess || {};
    const mine = config.mine || {};
    const k = mine.k;
    endpoint = endpointUrl(config.endpoint ?? "");
    seedProperty = preprocess.seed_property ?? "";
    minSupport = config.min_support ?? 10;
    propertyLimit = preprocess.property_limit ?? 50;
    maxTriples = preprocess.max_triples ?? 50000;
    numSubgraphs = mine.num_subgraphs ?? 30;
    if (typeof k === "number") {
      kRaw = String(k);
      kProbsRaw = "";
    } else if (k && typeof k === "object") {
      kRaw = Object.keys(k).join(", ");
      kProbsRaw = Object.values(k).join(", ");
    }
    maxSubgraphsPerSeed = mine.max_subgraphs_per_seed ?? 1;
    useCache = preprocess.use_cache ?? false;
    exactSupport = mine.exact_support ?? false;
    verifTimeout = mine.verif_timeout ?? 30;
    m = mine.m ?? 7;
    numAttrs = clonePresetValue(mine.num_attrs ?? [5, 9]);
    numAttrsRaw = Array.isArray(numAttrs)
      ? numAttrs.join(", ")
      : String(numAttrs);
    uniformTypes = mine.uniform_types ?? false;
    minimizePatterns = preprocess.minimize_patterns ?? true;
    randOffset = preprocess.rand_offset ?? false;
    includeClassesRaw = (preprocess.include_classes ?? []).join(", ");
    excludeClassesRaw = (preprocess.exclude_classes ?? []).join(", ");
    excludePropertiesRaw = (preprocess.exclude_properties ?? []).join(", ");
  }

  let selectedPreset = "dbpedia-notebook";
  let endpoint = "";
  let seedProperty = "";
  let minSupport = 10;
  let propertyLimit = 50;
  let maxTriples = 50000;
  let numSubgraphs = 30;
  let kRaw = "3";
  let kProbsRaw = "";
  let maxSubgraphsPerSeed = 1;
  let useCache = false;
  let exactSupport = false;
  let verifTimeout = 30;
  let m = 7;
  let numAttrs = [5, 9];
  let numAttrsRaw = "5, 9";
  let uniformTypes = false;
  let minimizePatterns = true;
  let randOffset = false;
  let includeClassesRaw = "";
  let excludeClassesRaw = "";
  let excludePropertiesRaw = "";
  let advancedOpen = false;

  $: if (defaults?.sampling?.endpoint && !endpoint)
    endpoint = defaults.sampling.endpoint;

  $: if (presetsLoaded && !presets[selectedPreset]) {
    selectedPreset = presets.custom ? "custom" : Object.keys(presets)[0];
  }

  $: if (presets[selectedPreset]) applyPreset(selectedPreset);

  function parseList(raw) {
    return raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }

  function parseNumAttrs(raw) {
    const nums = String(raw || "")
      .split(",")
      .map((s) => parseInt(s.trim(), 10))
      .filter((n) => !Number.isNaN(n));
    if (nums.length === 0) return [5, 9];
    if (nums.length === 1) return nums[0];
    return [nums[0], nums[1]];
  }

  function buildK() {
    const sizes = kRaw
      .split(",")
      .map((s) => parseInt(s.trim()))
      .filter((n) => !isNaN(n));
    const probs = kProbsRaw
      .split(",")
      .map((s) => parseFloat(s.trim()))
      .filter((n) => !isNaN(n));
    if (sizes.length === 1 && probs.length === 0) return sizes[0];
    const result = {};
    sizes.forEach((size, i) => {
      result[size] = probs[i] ?? 1;
    });
    return result;
  }

  function slugify(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/["']/g, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  function sampleRunTitle(preset) {
    const titleSource =
      selectedPreset !== "custom" ? preset?.label || selectedPreset : endpoint;
    return `querybloom-sample-${slugify(titleSource) || "custom"}`;
  }

  function submit() {
    if (!presetsLoaded) return;
    const preset = presets[selectedPreset] || null;
    const config = preset?.config || preset || {};
    const presetEndpoint = config.endpoint ?? preset?.endpoint ?? "";
    const presetEndpointUrl = endpointUrl(presetEndpoint);
    const shouldUsePresetAlias =
      selectedPreset !== "custom" &&
      presetEndpoint &&
      endpoint.trim() === presetEndpointUrl;
    onStart({
      title: sampleRunTitle(preset),
      config: {
        endpoint: shouldUsePresetAlias ? presetEndpoint : endpoint,
        min_support: Number(minSupport),
        preprocess: {
          property_limit: Number(propertyLimit),
          max_triples: Number(maxTriples),
          seed_property: seedProperty.trim() || null,
          minimize_patterns: minimizePatterns,
          rand_offset: randOffset,
          use_cache: useCache,
          include_classes: parseList(includeClassesRaw).length
            ? parseList(includeClassesRaw)
            : null,
          exclude_classes: parseList(excludeClassesRaw).length
            ? parseList(excludeClassesRaw)
            : null,
          exclude_properties: parseList(excludePropertiesRaw).length
            ? parseList(excludePropertiesRaw)
            : null,
        },
        mine: {
          k: buildK(),
          num_subgraphs: Number(numSubgraphs),
          output_dir: null,
          exact_support: exactSupport,
          m: Number(m),
          max_subgraphs_per_seed: Number(maxSubgraphsPerSeed),
          verif_timeout: Number(verifTimeout),
          prob_optional: 0,
          num_attrs: parseNumAttrs(numAttrsRaw),
          max_attr_len: 200,
          strategy: "rand",
          uniform_types: uniformTypes,
        },
        graph_limit: 1000,
      },
    });
  }
</script>

<form class="launcher" on:submit|preventDefault={submit}>
  <div class="header-row">
    <div>
      <h2>New sampling run</h2>
      <p>Discover properties, form patterns, and stream subgraphs live.</p>
    </div>
    <button type="submit" disabled={!presetsLoaded}>Start</button>
  </div>

  {#if defaultsError}
    <p class="error">{defaultsError}</p>
  {/if}

  <label>
    <span class="label-row">
      <span class="label-text">{fieldLabel("preset", "Preset")}</span>
      <FieldHelp
        description={fieldDescription(
          "preset",
          "Loads a starter sampling configuration for a known knowledge graph. Choose Custom to edit from scratch.",
        )}
      />
    </span>
    <select bind:value={selectedPreset}>
      {#each Object.entries(presets) as [presetId, preset]}
        <option value={presetId}>{preset.label}</option>
      {/each}
    </select>
  </label>

  <label>
    <span class="label-row">
      <span class="label-text">{fieldLabel("endpoint", "Endpoint")}</span>
      <FieldHelp
        description={fieldDescription(
          "endpoint",
          "SPARQL endpoint name or URL the backend will query. Presets use aliases from the backend config.",
        )}
      />
    </span>
    <input
      bind:value={endpoint}
      placeholder="dblp, dbpedia, sockg-local"
      required
    />
  </label>

  <div class="grid">
    <label>
      <span class="label-row">
        <span class="label-text"
          >{fieldLabel("min_support", "Min support")}</span
        >
        <FieldHelp
          description={fieldDescription(
            "min_support",
            "Minimum occurrence count required for a type-predicate-type pattern to be kept.",
          )}
        />
      </span>
      <input bind:value={minSupport} type="number" min="1" />
    </label>
    <label>
      <span class="label-row">
        <span class="label-text"
          >{fieldLabel("mine.num_subgraphs", "Subgraphs")}</span
        >
        <FieldHelp
          description={fieldDescription(
            "mine.num_subgraphs",
            "Target number of representative subgraphs to mine after ABSTAT preprocessing.",
          )}
        />
      </span>
      <input bind:value={numSubgraphs} type="number" min="1" />
    </label>
  </div>

  <button
    class="plain"
    type="button"
    on:click={() => (advancedOpen = true)}
  >
    Show advanced sampling settings
  </button>
</form>

{#if advancedOpen}
  <div
    class="modal-backdrop"
    role="presentation"
    on:click={() => (advancedOpen = false)}
    on:keydown={(e) => e.key === "Escape" && (advancedOpen = false)}
  >
    <div
      class="modal-card"
      role="dialog"
      tabindex="-1"
      aria-modal="true"
      aria-labelledby="advanced-sampling-title"
      on:click|stopPropagation
      on:keydown|stopPropagation
    >
      <div class="modal-header">
        <div class="modal-title-wrap">
          <h3 id="advanced-sampling-title">Advanced sampling settings</h3>
        </div>
        <button
          class="modal-close-btn"
          type="button"
          aria-label="Close"
          on:click={() => (advancedOpen = false)}>✕</button
        >
      </div>
      <div class="modal-body">
        <section class="advanced-section">
          <h4>Mining</h4>
          <div class="advanced">
            <label>
              <span class="label-row">
                <span class="label-text"
                  >{fieldLabel("mine.k", "Concept sizes")}</span
                >
                <FieldHelp
                  description={fieldDescription(
                    "mine.k",
                    "Allowed subgraph sizes by number of types. Use one number or comma-separated sizes. Pair with type size weights.",
                  )}
                />
              </span>
              <input bind:value={kRaw} placeholder="3, 4, 5" />
            </label>
            <label>
              <span class="label-row">
                <span class="label-text"
                  >{fieldLabel("mine.k_weights", "Type size weights")}</span
                >
                <FieldHelp
                  description={fieldDescription(
                    "mine.k_weights",
                    "Optional comma-separated weights matching the type sizes. They are normalized automatically to bias sampled subgraph sizes.",
                  )}
                />
              </span>
              <input bind:value={kProbsRaw} placeholder="0.2, 0.5, 0.3" />
            </label>
            <label>
              <span class="label-row">
                <span class="label-text"
                  >{fieldLabel(
                    "mine.max_subgraphs_per_seed",
                    "Max subgraphs per seed",
                  )}</span
                >
                <FieldHelp
                  description={fieldDescription(
                    "mine.max_subgraphs_per_seed",
                    "Maximum successful subgraphs allowed from a single start pattern. 1 is a hard cap near the pattern-pool size.",
                  )}
                />
              </span>
              <input bind:value={maxSubgraphsPerSeed} type="number" min="1" />
            </label>
            <label>
              <span class="label-row">
                <span class="label-text"
                  >{fieldLabel("mine.m", "Entities per type (m)")}</span
                >
                <FieldHelp
                  description={fieldDescription(
                    "mine.m",
                    "Number of sample entities fetched per type when verifying and instantiating a candidate subgraph.",
                  )}
                />
              </span>
              <input bind:value={m} type="number" min="1" />
            </label>
            <label>
              <span class="label-row">
                <span class="label-text"
                  >{fieldLabel(
                    "mine.num_attrs",
                    "Attributes per subgraph",
                  )}</span
                >
                <FieldHelp
                  description={fieldDescription(
                    "mine.num_attrs",
                    "How many data attributes to attach per subgraph. Use one number or a min, max pair such as 20, 25.",
                  )}
                />
              </span>
              <input bind:value={numAttrsRaw} placeholder="20, 25" />
            </label>
            <label>
              <span class="label-row">
                <span class="label-text"
                  >{fieldLabel(
                    "mine.verif_timeout",
                    "Verification timeout (s)",
                  )}</span
                >
                <FieldHelp
                  description={fieldDescription(
                    "mine.verif_timeout",
                    "Seconds allowed for each SPARQL support-verification query before the candidate is skipped.",
                  )}
                />
              </span>
              <input bind:value={verifTimeout} type="number" min="1" />
            </label>
            <label class="toggle-row">
              <span class="label-row">
                <span class="label-text"
                  >{fieldLabel("mine.exact_support", "Exact support")}</span
                >
                <FieldHelp
                  description={fieldDescription(
                    "mine.exact_support",
                    "If enabled, compute exact pattern support instead of the faster LIMIT-based estimate.",
                  )}
                />
              </span>
              <input bind:checked={exactSupport} type="checkbox" />
            </label>
            <label class="toggle-row">
              <span class="label-row">
                <span class="label-text"
                  >{fieldLabel("mine.uniform_types", "Uniform types")}</span
                >
                <FieldHelp
                  description={fieldDescription(
                    "mine.uniform_types",
                    "Sample type combinations more uniformly instead of biasing toward frequent patterns.",
                  )}
                />
              </span>
              <input bind:checked={uniformTypes} type="checkbox" />
            </label>
          </div>
        </section>

        <section class="advanced-section">
          <h4>Preprocessing</h4>
          <div class="advanced">
            <label class="toggle-row">
              <span class="label-row">
                <span class="label-text"
                  >{fieldLabel("preprocess.use_cache", "Use cache")}</span
                >
                <FieldHelp
                  description={fieldDescription(
                    "preprocess.use_cache",
                    "Reuse cached property and pattern results when available to avoid re-querying the endpoint.",
                  )}
                />
              </span>
              <input bind:checked={useCache} type="checkbox" />
            </label>
            <label class="toggle-row">
              <span class="label-row">
                <span class="label-text"
                  >{fieldLabel(
                    "preprocess.minimize_patterns",
                    "Minimize patterns",
                  )}</span
                >
                <FieldHelp
                  description={fieldDescription(
                    "preprocess.minimize_patterns",
                    "Apply paper-style instance-level type minimization. This can be expensive because it may prefetch subclass hierarchies and run additional type checks.",
                  )}
                />
              </span>
              <input bind:checked={minimizePatterns} type="checkbox" />
            </label>
            <label class="toggle-row">
              <span class="label-row">
                <span class="label-text"
                  >{fieldLabel("preprocess.rand_offset", "Random offset")}</span
                >
                <FieldHelp
                  description={fieldDescription(
                    "preprocess.rand_offset",
                    "Randomize the triple-scan offset per property so pattern estimates are not always taken from the start of the endpoint results.",
                  )}
                />
              </span>
              <input bind:checked={randOffset} type="checkbox" />
            </label>
            <label class="full">
              <span class="label-row">
                <span class="label-text"
                  >{fieldLabel("preprocess.seed_property", "Seed property")}</span
                >
                <FieldHelp
                  description={fieldDescription(
                    "preprocess.seed_property",
                    "Optional predicate URI used to start BFS-style property discovery near a known relation. Leave empty for the normal property scan.",
                  )}
                />
              </span>
              <input
                bind:value={seedProperty}
                placeholder="Optional property URI for dynamic discovery"
              />
            </label>
            <label>
              <span class="label-row">
                <span class="label-text"
                  >{fieldLabel("preprocess.property_limit", "Property limit")}</span
                >
                <FieldHelp
                  description={fieldDescription(
                    "preprocess.property_limit",
                    "Maximum number of properties to inspect during preprocessing, or the BFS expansion budget when using a seed property.",
                  )}
                />
              </span>
              <input bind:value={propertyLimit} type="number" min="1" />
            </label>
            <label>
              <span class="label-row">
                <span class="label-text"
                  >{fieldLabel(
                    "preprocess.max_triples",
                    "Max triples per property",
                  )}</span
                >
                <FieldHelp
                  description={fieldDescription(
                    "preprocess.max_triples",
                    "Maximum triples sampled for each property when estimating pattern counts.",
                  )}
                />
              </span>
              <input bind:value={maxTriples} type="number" min="1" />
            </label>
            <label class="full">
              <span class="label-row">
                <span class="label-text"
                  >{fieldLabel(
                    "preprocess.include_classes",
                    "Include class prefixes",
                  )}</span
                >
                <FieldHelp
                  description={fieldDescription(
                    "preprocess.include_classes",
                    "Only keep patterns whose classes start with one of these comma-separated URI prefixes.",
                  )}
                />
              </span>
              <input
                bind:value={includeClassesRaw}
                placeholder="http://dbpedia.org/ontology/, ..."
              />
            </label>
            <label class="full">
              <span class="label-row">
                <span class="label-text"
                  >{fieldLabel(
                    "preprocess.exclude_classes",
                    "Exclude class prefixes",
                  )}</span
                >
                <FieldHelp
                  description={fieldDescription(
                    "preprocess.exclude_classes",
                    "Drop patterns whose classes start with one of these comma-separated URI prefixes.",
                  )}
                />
              </span>
              <input
                bind:value={excludeClassesRaw}
                placeholder="http://www.w3.org/2002/07/owl#, ..."
              />
            </label>
            <label class="full">
              <span class="label-row">
                <span class="label-text"
                  >{fieldLabel(
                    "preprocess.exclude_properties",
                    "Exclude property substrings",
                  )}</span
                >
                <FieldHelp
                  description={fieldDescription(
                    "preprocess.exclude_properties",
                    "Skip properties whose URI contains any of these comma-separated substrings.",
                  )}
                />
              </span>
              <input
                bind:value={excludePropertiesRaw}
                placeholder="label, description, identifier"
              />
            </label>
          </div>
        </section>
      </div>
      <div class="modal-actions">
        <button
          class="modal-primary-btn"
          type="button"
          on:click={() => (advancedOpen = false)}>Done</button
        >
      </div>
    </div>
  </div>
{/if}

<style>
  .launcher {
    display: grid;
    gap: 14px;
    padding: 16px;
    border-bottom: 1px solid var(--border-default);
  }

  .header-row {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
  }

  h2,
  p {
    margin: 0;
  }

  h2 {
    color: var(--color-uni-dark-blue);
    font-size: 1rem;
  }

  p {
    color: #66708a;
    font-size: 0.82rem;
  }

  .error {
    color: #b42318;
    background: #fef3f2;
    border: 1px solid #fecdca;
    border-radius: 6px;
    padding: 8px 10px;
  }

  button[type="submit"]:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  label {
    display: grid;
    gap: 5px;
  }

  .label-row {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }

  .label-text {
    color: #56617f;
    font-size: 0.74rem;
    font-weight: 800;
    text-transform: uppercase;
  }

  input {
    width: 100%;
    border: 1px solid #d8deed;
    border-radius: 6px;
    padding: 8px 9px;
    color: #151a2b;
    font: inherit;
    font-size: 0.9rem;
  }

  select {
    width: 100%;
    border: 1px solid #d8deed;
    border-radius: 6px;
    padding: 8px 9px;
    color: #151a2b;
    font: inherit;
    font-size: 0.9rem;
    background: #fff;
  }

  .grid,
  .advanced {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
  }

  .advanced-section {
    display: grid;
    gap: 10px;
  }

  .advanced-section h4 {
    margin: 0;
    color: var(--color-uni-dark-blue);
    font-size: 0.78rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .full {
    grid-column: 1 / -1;
  }

  .modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: 9999;
    background: rgba(15, 23, 42, 0.65);
    backdrop-filter: blur(4px);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
  }

  .modal-card {
    background: #ffffff;
    border-radius: 12px;
    box-shadow:
      0 20px 25px -5px rgba(0, 0, 0, 0.2),
      0 10px 10px -5px rgba(0, 0, 0, 0.1);
    border: 1px solid #e2e8f0;
    max-width: 760px;
    width: 100%;
    max-height: min(88vh, 900px);
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    background: #f8fafc;
    border-bottom: 1px solid #e2e8f0;
  }

  .modal-title-wrap h3 {
    margin: 0;
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--color-uni-dark-blue);
  }

  .modal-close-btn {
    background: transparent;
    border: none;
    font-size: 1.1rem;
    color: #a0aec0;
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 4px;
    line-height: 1;
  }

  .modal-close-btn:hover {
    color: #4a5568;
    background: #edf2f7;
  }

  .modal-body {
    display: grid;
    gap: 18px;
    padding: 16px 20px 8px;
    overflow: auto;
  }

  .modal-actions {
    display: flex;
    justify-content: flex-end;
    padding: 12px 20px 16px;
    border-top: 1px solid #e2e8f0;
  }

  .modal-primary-btn {
    background: var(--color-uni-blue);
  }

  .toggle-row {
    align-content: start;
  }

  .toggle-row input {
    width: auto;
    justify-self: start;
    accent-color: var(--color-uni-green);
  }

  button {
    border: 0;
    border-radius: 6px;
    padding: 8px 12px;
    background: var(--color-uni-blue);
    color: #fff;
    cursor: pointer;
    font-weight: 800;
  }

  .plain {
    justify-self: flex-start;
    padding: 0;
    background: transparent;
    color: var(--color-uni-blue);
  }

  @media (max-width: 920px) {
    .grid,
    .advanced {
      grid-template-columns: 1fr;
    }
  }
</style>
