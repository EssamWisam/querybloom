<script>
  import FieldHelp from "./FieldHelp.svelte";
  import endpointCatalog from "$endpoints";

  export let defaults = null;
  export let onStart = () => {};

  const CLIMATEMODELSKG_PRESET_CONFIG = {
    endpoint: "climatemodelskg",
    min_support: 5,
    preprocess: {
      property_limit: 300,
      max_triples: 30000,
      seed_property: "",
      minimize_patterns: true,
      rand_offset: true,
      use_cache: false,
      include_classes: [],
      exclude_classes: [],
      exclude_properties: ["label", "description", "identifier"],
    },
    mine: {
      k: { 2: 0.1, 3: 0.4, 4: 0.3, 5: 0.2 },
      num_subgraphs: 120,
      max_subgraphs_per_seed: 3,
      exact_support: false,
      verif_timeout: 10,
      m: 10,
      num_attrs: [6, 10],
      uniform_types: false,
    },
  };

  function isFrinkEndpoint(endpoint) {
    if (typeof endpoint === "string") return true;
    if (endpoint && typeof endpoint === "object") {
      return Boolean(endpoint.url) && (endpoint.frink ?? true);
    }
    return false;
  }

  function isIntuitiveEndpoint(endpoint) {
    return (
      endpoint && typeof endpoint === "object" && endpoint.intuitive === true
    );
  }

  function endpointLabel(endpointId, endpoint) {
    if (endpoint && typeof endpoint === "object")
      return endpoint.title || endpointId;
    return endpointId;
  }

  function endpointUrl(endpointIdOrUrl) {
    const endpoint = endpointCatalog[endpointIdOrUrl];
    if (typeof endpoint === "string") return endpoint;
    if (endpoint && typeof endpoint === "object")
      return endpoint.url || endpointIdOrUrl;
    return endpointIdOrUrl;
  }

  function climatemodelskgConfigForEndpoint(endpointId) {
    const config = JSON.parse(JSON.stringify(CLIMATEMODELSKG_PRESET_CONFIG));
    config.endpoint = endpointId;
    return config;
  }

  const FRINK_PRESETS = Object.fromEntries(
    Object.entries(endpointCatalog)
      .filter(
        ([endpointId, endpoint]) =>
          endpointId !== "federated" &&
          isFrinkEndpoint(endpoint) &&
          isIntuitiveEndpoint(endpoint),
      )
      .map(([endpointId, endpoint]) => [
        endpointId,
        {
          label: endpointLabel(endpointId, endpoint),
          config: climatemodelskgConfigForEndpoint(endpointId),
        },
      ]),
  );

  const PRESETS = {
    custom: {
      label: "Custom",
      endpoint: "",
      minSupport: 10,
      propertyLimit: 50,
      maxTriples: 50000,
      seedProperty: "",
      minimizePatterns: true,
      randOffset: false,
      includeClasses: [],
      excludeClasses: [],
      excludeProperties: [],
      k: 3,
      numSubgraphs: 30,
      maxSubgraphsPerSeed: 1,
      useCache: false,
      exactSupport: false,
      verifTimeout: 30,
      m: 7,
      numAttrs: [5, 9],
      uniformTypes: false,
    },
    "dbpedia-notebook": {
      label: "DBPedia",
      endpoint: "dbpedia-qlever",
      minSupport: 100,
      propertyLimit: 1500,
      maxTriples: 30000,
      seedProperty: "http://dbpedia.org/ontology/spouse",
      minimizePatterns: true,
      randOffset: true,
      includeClasses: ["http://dbpedia.org/ontology/"],
      excludeClasses: [],
      excludeProperties: ["label", "description", "identifier"],
      k: { 3: 0.1, 4: 0.3, 5: 0.4, 6: 0.2 },
      numSubgraphs: 500,
      maxSubgraphsPerSeed: 1,
      useCache: false,
      exactSupport: false,
      verifTimeout: 20,
      m: 10,
      numAttrs: [9, 13],
      uniformTypes: true,
    },
    ...FRINK_PRESETS,
  };

  function mergePresets(configuredPresets) {
    if (!configuredPresets) return PRESETS;
    const { ["sockg-notebook"]: _legacyClimateModelsPreset, ...presets } =
      configuredPresets;
    return { ...PRESETS, ...presets, ...FRINK_PRESETS };
  }

  $: samplingUi = defaults?.ui?.sampling ?? {};
  $: samplingFields = samplingUi.fields ?? {};
  $: presets = mergePresets(samplingUi.presets);

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
    const preset = presets[presetId] || presets.custom || PRESETS.custom;
    const config = preset.config || preset;
    const preprocess = config.preprocess || {};
    const mine = config.mine || {};
    const k = mine.k ?? preset.k;
    endpoint = endpointUrl(config.endpoint ?? preset.endpoint ?? "");
    seedProperty = preprocess.seed_property ?? preset.seedProperty ?? "";
    minSupport = config.min_support ?? preset.minSupport ?? 10;
    propertyLimit = preprocess.property_limit ?? preset.propertyLimit ?? 50;
    maxTriples = preprocess.max_triples ?? preset.maxTriples ?? 50000;
    numSubgraphs = mine.num_subgraphs ?? preset.numSubgraphs ?? 30;
    if (typeof k === "number") {
      kRaw = String(k);
      kProbsRaw = "";
    } else if (k && typeof k === "object") {
      kRaw = Object.keys(k).join(", ");
      kProbsRaw = Object.values(k).join(", ");
    }
    maxSubgraphsPerSeed =
      mine.max_subgraphs_per_seed ?? preset.maxSubgraphsPerSeed ?? 1;
    useCache = preprocess.use_cache ?? preset.useCache ?? false;
    exactSupport = mine.exact_support ?? preset.exactSupport ?? false;
    verifTimeout = mine.verif_timeout ?? preset.verifTimeout ?? 30;
    m = mine.m ?? preset.m ?? 7;
    numAttrs = clonePresetValue(mine.num_attrs ?? preset.numAttrs ?? [5, 9]);
    uniformTypes = mine.uniform_types ?? preset.uniformTypes ?? false;
    minimizePatterns =
      preprocess.minimize_patterns ?? preset.minimizePatterns ?? true;
    randOffset = preprocess.rand_offset ?? preset.randOffset ?? false;
    includeClassesRaw = (
      preprocess.include_classes ??
      preset.includeClasses ??
      []
    ).join(", ");
    excludeClassesRaw = (
      preprocess.exclude_classes ??
      preset.excludeClasses ??
      []
    ).join(", ");
    excludePropertiesRaw = (
      preprocess.exclude_properties ??
      preset.excludeProperties ??
      []
    ).join(", ");
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
  let uniformTypes = false;
  let minimizePatterns = true;
  let randOffset = false;
  let includeClassesRaw = "";
  let excludeClassesRaw = "";
  let excludePropertiesRaw = "";
  let advancedOpen = false;

  $: if (defaults?.sampling?.endpoint && !endpoint)
    endpoint = defaults.sampling.endpoint;

  $: if (selectedPreset && presets) applyPreset(selectedPreset);

  function parseList(raw) {
    return raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
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
          num_attrs: numAttrs,
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
    <button type="submit">Start</button>
  </div>

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
    <label>
      <span class="label-row">
        <span class="label-text"
          >{fieldLabel("mine.k", "Types per subgraph")}</span
        >
        <FieldHelp
          description={fieldDescription(
            "mine.k",
            "Allowed subgraph sizes by number of types. Use one number or comma-separated sizes.",
          )}
        />
      </span>
      <input bind:value={kRaw} placeholder="3, 4, 5, 6" />
    </label>
  </div>

  <button
    class="plain"
    type="button"
    on:click={() => (advancedOpen = !advancedOpen)}
  >
    {advancedOpen ? "Hide" : "Show"} advanced sampling settings
  </button>

  {#if advancedOpen}
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
      <label class="full">
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
        <input bind:value={kProbsRaw} placeholder="0.1, 0.3, 0.4, 0.2" />
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
  {/if}
</form>

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
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
  }

  .advanced {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    padding: 12px;
    border: 1px solid #e4e8f4;
    border-radius: 8px;
    background: #fbfcff;
  }

  .full {
    grid-column: 1 / -1;
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
