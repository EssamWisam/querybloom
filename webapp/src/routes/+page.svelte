<script>
  import { onDestroy, onMount } from "svelte";
  import AuthPanel from "$lib/abstat/components/AuthPanel.svelte";
  import GraphSubgraphs from "$lib/abstat/components/GraphSubgraphs.svelte";
  import PatternsPanel from "$lib/abstat/components/PatternsPanel.svelte";
  import PropertiesPanel from "$lib/abstat/components/PropertiesPanel.svelte";
  import QaPanel from "$lib/abstat/components/QaPanel.svelte";
  import RunLauncher from "$lib/abstat/components/RunLauncher.svelte";
  import RunTimeline from "$lib/abstat/components/RunTimeline.svelte";
  import {
    cancelRun,
    cleanupStaleRuns,
    clearStoredSession,
    deleteRun,
    extractAccessToken,
    loadDefaults,
    loadRun,
    loadRunEvents,
    loadRunSubgraphs,
    loadRuns,
    loadStoredSession,
    saveStoredSession,
    skipDiscovery,
    skipSubgraphs,
    streamSampling,
  } from "$lib/abstat/api.js";
  import {
    edgeKey,
    normalizeGraph,
    upsertSubgraph,
  } from "$lib/abstat/graph.js";

  let session = null;
  let token = null;
  let authReady = false;
  let defaults = null;
  let runs = [];
  let activeTab = "live";
  let running = false;
  let streamError = "";
  let activeRun = null;
  let endpoint = "";
  let events = [];
  let graph = null;
  let subgraphs = [];
  let selectedSubgraphIndex = null;
  let properties = [];
  let propertySummary = {
    listedCount: 0,
    filteredCount: 0,
    discoveredTypeCount: 0,
    truncated: false,
    propertyCache: null,
    patternCache: null,
  };
  let sampleAbortController = null;
  let discoveryPhase = false;
  let miningPhase = false;
  let skipDiscoveryPending = false;
  let skipSubgraphsPending = false;
  let restoringRunId = null;
  let deletingRunId = null;
  let eventPollTimer = null;
  let pollingRunId = null;
  let pollingEvents = false;
  let seenStoredEventKeys = new Set();
  let seenFrameKeys = new Set();
  let seenSubgraphIndexes = new Set();
  let latestStoredEventCreatedAt = null;
  let railCollapsed = false;

  $: latestSampleRun =
    activeRun?.kind === "sample"
      ? activeRun
      : runs.find((run) => run.kind === "sample") || null;
  $: latestSampleRunId = latestSampleRun?.id || "";
  $: qaSampleRunId =
    activeRun?.kind === "llm"
      ? activeRun?.result?.sample_run_id || latestSampleRunId
      : latestSampleRunId;
  $: liveRunActive = running || pollingRunId === activeRun?.id;
  $: samplingRunActive = liveRunActive && activeRun?.kind === "sample";
  $: llmRunActive = liveRunActive && activeRun?.kind === "llm";
  $: propertiesTabBusy = samplingRunActive && discoveryPhase;
  $: patternsTabBusy = samplingRunActive && discoveryPhase;
  $: subgraphsTabBusy = samplingRunActive && miningPhase;
  $: qaTabBusy = llmRunActive;
  $: if (!liveRunActive || !discoveryPhase) skipDiscoveryPending = false;
  $: if (!liveRunActive || !miningPhase) skipSubgraphsPending = false;

  function resetRunWorkspace() {
    events = [];
    graph = null;
    subgraphs = [];
    selectedSubgraphIndex = null;
    properties = [];
    discoveryPhase = false;
    miningPhase = false;
    skipDiscoveryPending = false;
    skipSubgraphsPending = false;
    seenFrameKeys = new Set();
    seenSubgraphIndexes = new Set();
    latestStoredEventCreatedAt = null;
    propertySummary = {
      listedCount: 0,
      filteredCount: 0,
      discoveredTypeCount: 0,
      truncated: false,
      propertyCache: null,
      patternCache: null,
    };
  }

  function storedEventKey(row) {
    if (row?.id) return row.id;
    const payload = JSON.stringify(row?.payload || {});
    return [
      row?.event_type,
      row?.stage || "",
      row?.message || "",
      payload,
    ].join("|");
  }

  function frameEventKey(event, data) {
    const payload =
      data?.data ?? data?.payload ?? data?.result ?? data?.run?.id ?? {};
    return [
      event,
      data?.stage || "",
      data?.message || "",
      JSON.stringify(payload),
    ].join("|");
  }

  function freshGraphElements(previousGraph, nextGraph, sourceProperty = null) {
    const previous = normalizeGraph(previousGraph);
    const next = normalizeGraph(nextGraph);
    const previousNodeIds = new Set(
      previous.nodes.map((node) => String(node.data.id)),
    );
    const previousEdgeKeys = new Set(
      previous.edges.map((edge) =>
        edgeKey(
          edge.data.source,
          edge.data.predicate || edge.data.uri,
          edge.data.target,
        ),
      ),
    );
    const freshNodeIds = new Set();
    const freshEdgeKeys = new Set();

    for (const node of next.nodes) {
      const nodeId = String(node.data.id);
      if (!previousNodeIds.has(nodeId)) freshNodeIds.add(nodeId);
    }

    for (const edge of next.edges) {
      const predicate = edge.data.predicate || edge.data.uri;
      const key = edgeKey(edge.data.source, predicate, edge.data.target);
      const isNewEdge = !previousEdgeKeys.has(key);
      const isSourceProperty = sourceProperty && predicate === sourceProperty;
      if (isNewEdge || isSourceProperty) {
        freshEdgeKeys.add(key);
        freshNodeIds.add(String(edge.data.source));
        freshNodeIds.add(String(edge.data.target));
      }
    }

    return {
      freshNodeIds: [...freshNodeIds],
      freshEdgeKeys: [...freshEdgeKeys],
    };
  }

  function clearEventPolling() {
    if (eventPollTimer) clearInterval(eventPollTimer);
    eventPollTimer = null;
    pollingRunId = null;
    pollingEvents = false;
  }

  function setSession(nextSession) {
    session = nextSession;
    token = extractAccessToken(nextSession);
    saveStoredSession(nextSession);
    refreshRuns();
  }

  function logout() {
    clearEventPolling();
    session = null;
    token = null;
    clearStoredSession();
  }

  async function handleLogout() {
    if (
      running &&
      !confirm("A run is in progress. Logging out will interrupt it. Continue?")
    )
      return;
    if (running && token && activeRun?.id) {
      await cancelRun(token, activeRun.id).catch(() => {});
    }
    if (sampleAbortController) sampleAbortController.abort();
    logout();
  }

  async function refreshRuns() {
    if (!token) return;
    try {
      const cleanup = await cleanupStaleRuns(token).catch((e) => {
        console.warn("cleanup-stale failed:", e);
        return null;
      });
      if (cleanup?.cleaned)
        console.log(
          `[cleanup] marked ${cleanup.cleaned} stale run(s) as interrupted`,
        );
      const loadedRuns = await loadRuns(token, 25);
      runs = loadedRuns;
      if (activeRun?.id) {
        const latest = loadedRuns.find((run) => run.id === activeRun.id);
        if (latest) activeRun = latest;
        if (latest && latest.status !== "running") clearEventPolling();
      }
      return loadedRuns;
    } catch {
      runs = [];
      return [];
    }
  }

  async function pollRunEvents(runId) {
    if (!token || pollingEvents || activeRun?.id !== runId) return;
    pollingEvents = true;
    try {
      const storedEvents = await loadRunEvents(token, runId, {
        after: latestStoredEventCreatedAt,
        limit: 250,
      });
      if (Array.isArray(storedEvents)) {
        for (const row of storedEvents) {
          const key = storedEventKey(row);
          if (seenStoredEventKeys.has(key)) continue;
          seenStoredEventKeys.add(key);
          if (row.created_at) latestStoredEventCreatedAt = row.created_at;
          handleStreamFrame({
            event: row.event_type,
            data: {
              type: row.event_type,
              stage: row.stage,
              message: row.message,
              timestamp: row.created_at,
              data: row.payload,
            },
          });
        }
      }
      const storedSubgraphs = await loadRunSubgraphs(token, runId);
      if (Array.isArray(storedSubgraphs)) {
        for (const row of storedSubgraphs) {
          const idx = row.subgraph_index;
          if (typeof idx !== "number" || seenSubgraphIndexes.has(idx)) continue;
          seenSubgraphIndexes.add(idx);
          handleStreamFrame({
            event: "subgraph.discovered",
            data: {
              type: "subgraph.discovered",
              stage: "mining",
              data: {
                index: idx,
                dbId: row.id,
                subgraph: row.payload,
                graph: row.graph,
                support: row.support,
              },
            },
          });
        }
      }
      const latest = await loadRun(token, runId).catch(() => null);
      if (latest) activeRun = latest;
      if (!latest || latest.status !== "running") clearEventPolling();
    } catch (err) {
      console.warn("run event polling failed:", err);
    } finally {
      pollingEvents = false;
    }
  }

  function startEventPolling(runId) {
    if (!runId || pollingRunId === runId) return;
    clearEventPolling();
    pollingRunId = runId;
    pollRunEvents(runId);
    eventPollTimer = setInterval(() => pollRunEvents(runId), 2000);
  }

  async function handleRefreshRuns() {
    const loadedRuns = await refreshRuns();
    const currentRun = activeRun
      ? loadedRuns?.find((run) => run.id === activeRun.id)
      : null;
    if (currentRun?.status === "running") {
      startEventPolling(currentRun.id);
    } else if (!activeRun) {
      const activeSample = loadedRuns?.find(
        (run) => run.kind === "sample" && run.status === "running",
      );
      if (activeSample) await restoreRun(activeSample);
    }
  }

  function addEvent(event, data) {
    const payload = data?.data || data || {};
    events = [
      ...events.slice(-499),
      {
        id: `${events.length}-${event}-${Date.now()}`,
        event,
        type: data?.type || event,
        stage: data?.stage,
        message: data?.message,
        timestamp: data?.timestamp || new Date().toISOString(),
        payload,
      },
    ];
  }

  function displayStreamError(message, fallback = "Sampling run failed") {
    const text = String(message || "").trim();
    if (!text) return fallback;
    if (text.includes("Error parsing CSV response")) return fallback;
    const propertyFailure = text.match(
      /^Failed to fetch properties from ([^:]+|https?:\/\/\S+):/,
    );
    if (propertyFailure)
      return `Failed to fetch properties from ${propertyFailure[1]}.`;
    return text;
  }

  function upsertProperty(next) {
    if (!next?.uri) return;
    const index = properties.findIndex((item) => item.uri === next.uri);
    if (index === -1) {
      properties = [...properties, next];
      return;
    }

    const updated = [...properties];
    updated[index] = { ...updated[index], ...next };
    properties = updated;
  }

  async function cancelSampling() {
    if (!liveRunActive) return;
    addEvent("run.cancel.requested", {
      stage: "sampling",
      message:
        "Cancellation requested. Waiting for the backend to stop mining.",
      timestamp: new Date().toISOString(),
    });
    discoveryPhase = false;
    miningPhase = false;
    const cancelRequest =
      token && activeRun?.id
        ? cancelRun(token, activeRun.id)
        : Promise.resolve();
    if (sampleAbortController) sampleAbortController.abort();
    if (token && activeRun?.id) {
      await cancelRequest.catch((error) => {
        streamError =
          error?.message || "Could not cancel the run on the backend";
      });
    }
  }

  function handleStreamFrame({ event, data }) {
    const frameData =
      event === "error" && data?.error && !data?.message
        ? { ...data, stage: data.stage || "sampling", message: data.error }
        : data;
    const key = frameEventKey(event, frameData);
    if (seenFrameKeys.has(key)) return;
    seenFrameKeys.add(key);
    addEvent(event, frameData);
    const payload = frameData?.data || frameData || {};

    if (event === "error") {
      streamError = displayStreamError(
        frameData?.message || payload.error,
        "Sampling run failed",
      );
      discoveryPhase = false;
      miningPhase = false;
    }

    if (event === "run.created" && frameData?.run) activeRun = frameData.run;
    if (event === "result" && frameData?.run) activeRun = frameData.run;
    if (event === "stage.started" && frameData?.stage === "preprocess")
      discoveryPhase = true;
    if (event === "stage.completed" && frameData?.stage === "preprocess")
      discoveryPhase = false;
    if (event === "stage.started" && frameData?.stage === "mining") {
      discoveryPhase = false;
      miningPhase = true;
    }
    if (event === "stage.completed" && frameData?.stage === "mining")
      miningPhase = false;
    if (event === "stage.skipped" && frameData?.stage === "mining")
      miningPhase = false;
    if (event === "properties.list") {
      propertySummary = {
        ...propertySummary,
        listedCount: payload.count || 0,
        frequencyFetched: payload.frequency === true,
        truncated: Boolean(payload.truncated),
      };
      properties = (payload.properties || []).map((item) => ({
        ...item,
        status: "queued",
      }));
    }
    if (event === "properties.filtered") {
      propertySummary = {
        ...propertySummary,
        filteredCount: payload.count || 0,
      };
    }
    if (event === "property.started") {
      upsertProperty({
        uri: payload.uri,
        label: payload.label,
        short_name: payload.short_name,
        status: "processing",
        updated_at: frameData?.timestamp,
      });
    }
    if (event === "property.completed") {
      upsertProperty({
        uri: payload.uri,
        label: payload.label,
        short_name: payload.short_name,
        status: "completed",
        num_new_types: payload.num_new_types,
        added_object_patterns: payload.added_object_patterns,
        added_attribute_patterns: payload.added_attribute_patterns,
        total_object_patterns: payload.total_object_patterns,
        total_attribute_patterns: payload.total_attribute_patterns,
        updated_at: frameData?.timestamp,
      });
    }
    if (event === "properties.discovered") {
      propertySummary = {
        ...propertySummary,
        discoveredTypeCount: payload.discovered_type_count || 0,
      };
    }
    if (event === "cache.loaded") {
      if (frameData?.stage === "abstat.properties") {
        propertySummary = {
          ...propertySummary,
          propertyCache: {
            loaded: true,
            path: payload.path,
            count: payload.count || 0,
          },
        };
      }
      if (frameData?.stage === "abstat.patterns") {
        propertySummary = {
          ...propertySummary,
          patternCache: {
            loaded: true,
            path: payload.path,
            objectCount: payload.num_object_patterns || 0,
            attributeCount: payload.num_attribute_patterns || 0,
          },
        };
      }
    }
    if (
      event === "graph.updated" &&
      payload.graph &&
      (payload.num_patterns ?? 0) > 0
    ) {
      const fresh = freshGraphElements(
        graph,
        payload.graph,
        payload.source_property ?? null,
      );
      graph = {
        ...payload.graph,
        latestProperty: payload.source_property ?? null,
        freshNodeIds: fresh.freshNodeIds,
        freshEdgeKeys: fresh.freshEdgeKeys,
        updatedAt: frameData?.timestamp || new Date().toISOString(),
        numPatterns: payload.num_patterns ?? null,
        numAttributePatterns: payload.num_attribute_patterns ?? null,
      };
    }
    if (event === "subgraph.discovered") {
      subgraphs = upsertSubgraph(subgraphs, {
        index: payload.index,
        subgraph: payload.subgraph,
        graph: payload.graph,
        support: payload.support,
        numTypes: payload.subgraph?.num_types,
      });
      if (selectedSubgraphIndex == null)
        selectedSubgraphIndex = Number(payload.index || 0);
    }
    if (event === "subgraph.samples") {
      subgraphs = upsertSubgraph(subgraphs, {
        index: payload.index,
        samples: payload.samples || payload,
      });
    }
  }

  async function handleSkipDiscovery() {
    if (!token || !activeRun?.id || skipDiscoveryPending) return;
    skipDiscoveryPending = true;
    try {
      await skipDiscovery(token, activeRun.id);
    } catch (error) {
      skipDiscoveryPending = false;
      console.warn("skip discovery failed:", error);
    }
  }

  async function handleSkipSubgraphs() {
    if (!token || !activeRun?.id || skipSubgraphsPending) return;
    skipSubgraphsPending = true;
    try {
      await skipSubgraphs(token, activeRun.id);
    } catch (error) {
      skipSubgraphsPending = false;
      console.warn("skip subgraphs failed:", error);
    }
  }

  async function handleDeleteRun(run) {
    if (deletingRunId) return;
    deletingRunId = run.id;
    try {
      await deleteRun(token, run.id);
      runs = runs.filter((r) => r.id !== run.id);
      if (activeRun?.id === run.id) {
        clearEventPolling();
        activeRun = null;
      }
    } finally {
      deletingRunId = null;
    }
  }

  async function restoreRun(run) {
    if (running || restoringRunId) return;
    clearEventPolling();
    restoringRunId = run.id;
    streamError = "";
    activeRun = run;
    endpoint = run.endpoint || run.config?.endpoint || "";
    resetRunWorkspace();
    try {
      const targetSampleRunId =
        run.kind === "llm"
          ? run.config?.sample_run_id || run.result?.sample_run_id || run.id
          : run.id;

      const [storedEvents, storedSubgraphs] = await Promise.all([
        loadRunEvents(token, run.id),
        loadRunSubgraphs(token, targetSampleRunId),
      ]);
      if (Array.isArray(storedEvents)) {
        for (const row of storedEvents) {
          seenStoredEventKeys.add(storedEventKey(row));
          if (row.created_at) latestStoredEventCreatedAt = row.created_at;
          handleStreamFrame({
            event: row.event_type,
            data: {
              type: row.event_type,
              stage: row.stage,
              message: row.message,
              timestamp: row.created_at,
              data: row.payload,
            },
          });
        }
      }
      if (Array.isArray(storedSubgraphs) && storedSubgraphs.length > 0) {
        for (const row of storedSubgraphs) {
          const idx = row.subgraph_index;
          if (typeof idx !== "number") continue;
          seenSubgraphIndexes.add(idx);
          handleStreamFrame({
            event: "subgraph.discovered",
            data: {
              type: "subgraph.discovered",
              stage: "mining",
              data: {
                index: idx,
                dbId: row.id,
                subgraph: row.payload || row,
                graph: row.graph,
                support: row.support,
              },
            },
          });
        }
      } else if (Array.isArray(run.result?.subgraphs) && run.result.subgraphs.length > 0) {
        for (let idx = 0; idx < run.result.subgraphs.length; idx++) {
          const sg = run.result.subgraphs[idx];
          const actualIdx =
            typeof sg?.source_subgraph_index === "number"
              ? sg.source_subgraph_index
              : typeof sg?.index === "number"
                ? sg.index
                : idx;
          seenSubgraphIndexes.add(actualIdx);
          handleStreamFrame({
            event: "subgraph.discovered",
            data: {
              type: "subgraph.discovered",
              stage: "mining",
              data: {
                index: actualIdx,
                subgraph: sg,
                graph: sg?.graph,
                support: sg?.support,
              },
            },
          });
        }
      }
    } catch {
      // silently ignore restore errors
    } finally {
      restoringRunId = null;
    }
    if (run.status === "running") startEventPolling(run.id);
  }

  async function startSampling(payload) {
    if (!token) return;
    streamError = "";
    running = true;
    discoveryPhase = false;
    sampleAbortController = new AbortController();
    activeTab = "live";
    activeRun = null;
    endpoint = payload.config.endpoint;
    clearEventPolling();
    resetRunWorkspace();
    try {
      await streamSampling(
        token,
        payload,
        handleStreamFrame,
        sampleAbortController.signal,
      );
      await refreshRuns();
    } catch (err) {
      if (err?.name === "AbortError") {
        await refreshRuns();
      } else {
        streamError = displayStreamError(
          err?.message,
          "Sampling stream failed",
        );
      }
    } finally {
      running = false;
      sampleAbortController = null;
      clearEventPolling();
    }
  }

  onMount(async () => {
    const stored = loadStoredSession();
    if (stored) {
      session = stored;
      token = extractAccessToken(stored);
      await handleRefreshRuns();
    }
    defaults = await loadDefaults().catch(() => null);
    authReady = true;
  });

  onDestroy(() => {
    clearEventPolling();
  });
</script>

{#if !authReady}
  <main class="boot-shell">
    <section class="boot-panel">
      <p>Loading session...</p>
    </section>
  </main>
{:else if !token}
  <AuthPanel onAuthenticated={setSession} />
{:else}
  <main class="workbench" class:rail-collapsed={railCollapsed}>
    <aside class="rail" class:collapsed={railCollapsed}>
      <header>
        <div class="brand-block">
          <p>QueryBloom</p>
          <h1>Workbench</h1>
        </div>
        <div class="rail-actions">
          <button
            class="rail-toggle"
            type="button"
            aria-label={railCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={railCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            on:click={() => (railCollapsed = !railCollapsed)}
            ><span aria-hidden="true">{railCollapsed ? ">" : "<"}</span></button
          >
          {#if !railCollapsed}
            <button type="button" on:click={handleLogout}>Logout</button>
          {/if}
        </div>
      </header>
      {#if railCollapsed}
        <div class="collapsed-mark" aria-hidden="true">QB</div>
      {:else}
        <RunLauncher {defaults} onStart={startSampling} />
        <section class="runs">
          <div class="runs-header">
            <h2>Recent runs</h2>
            <button type="button" on:click={handleRefreshRuns}>Refresh</button>
          </div>
          {#if !runs.length}
            <p class="muted">No runs loaded yet.</p>
          {/if}
          {#each runs as run (run.id)}
            <article
              class:active={activeRun?.id === run.id}
              class:restoring={restoringRunId === run.id}
              class:run-active={run.status === "running"}
            >
              <div class="run-row">
                <button
                  class="run-select"
                  type="button"
                  on:click={() => restoreRun(run)}
                >
                  <strong>{run.title || run.kind}</strong>
                  <span
                    class="run-status"
                    class:is-running={run.status === "running"}
                  >
                    {run.status} · {run.endpoint || "endpoint"}
                    {#if run.result?.num_patterns != null}
                      · {run.result.num_patterns} patterns
                    {/if}
                    {#if run.result?.num_subgraphs != null}
                      · {run.result.num_subgraphs} subgraphs
                    {/if}
                  </span>
                  {#if run.created_at}
                    <span class="run-ts"
                      >{new Date(run.created_at).toLocaleString()}</span
                    >
                  {/if}
                </button>
                {#if restoringRunId === run.id}
                  <span class="spinner" aria-label="Loading"></span>
                {:else}
                  <button
                    class="delete-run"
                    type="button"
                    aria-label="Delete run"
                    disabled={!!deletingRunId}
                    on:click|stopPropagation={() => handleDeleteRun(run)}
                    >✕</button
                  >
                {/if}
              </div>
            </article>
          {/each}
        </section>
      {/if}
    </aside>

    <section class="main-panel">
      <nav class="tabs" aria-label="Run workspace tabs">
        <div class="tab-sequence" aria-label="Sampling workflow sequence">
          <button
            class:active={activeTab === "properties"}
            type="button"
            on:click={() => (activeTab = "properties")}
            >{#if propertiesTabBusy}<span
                class="spinner tab-spinner"
                aria-hidden="true"
              ></span>{/if}Properties</button
          >
          <span class="tab-arrow" aria-hidden="true">→</span>
          <button
            class:active={activeTab === "patterns"}
            type="button"
            on:click={() => (activeTab = "patterns")}
            >{#if patternsTabBusy}<span
                class="spinner tab-spinner"
                aria-hidden="true"
              ></span>{/if}Patterns</button
          >
          <span class="tab-arrow" aria-hidden="true">→</span>
          <button
            class:active={activeTab === "subgraphs"}
            type="button"
            on:click={() => (activeTab = "subgraphs")}
            >{#if subgraphsTabBusy}<span
                class="spinner tab-spinner"
                aria-hidden="true"
              ></span>{/if}Subgraphs</button
          >
          <span class="tab-arrow" aria-hidden="true">→</span>
          <button
            class:active={activeTab === "qa"}
            type="button"
            on:click={() => (activeTab = "qa")}
            >{#if qaTabBusy}<span class="spinner tab-spinner" aria-hidden="true"
              ></span>{/if}Text-Query</button
          >
        </div>
        <button
          class:active={activeTab === "live"}
          class:logs-tab={true}
          type="button"
          on:click={() => (activeTab = "live")}
          >{#if liveRunActive}<span
              class="spinner tab-spinner"
              aria-hidden="true"
            ></span>{/if}Logs</button
        >
        {#if liveRunActive}
          <button class="interrupt" type="button" on:click={cancelSampling}
            >Stop run</button
          >
        {/if}
      </nav>

      {#if streamError}<p class="stream-error">{streamError}</p>{/if}

      <div class="tab-body">
        {#if activeTab === "live"}
          <div class="tab-panel-shell">
            <RunTimeline {events} running={liveRunActive} />
          </div>
        {:else if activeTab === "properties"}
          <div class="tab-panel-shell">
            <PropertiesPanel
              {properties}
              summary={propertySummary}
              running={liveRunActive}
            />
          </div>
        {:else if activeTab === "patterns"}
          <div class="tab-panel-shell">
            <PatternsPanel
              {graph}
              {properties}
              summary={propertySummary}
              running={liveRunActive}
              {discoveryPhase}
              {skipDiscoveryPending}
              onSkipDiscovery={handleSkipDiscovery}
            />
          </div>
        {:else if activeTab === "subgraphs"}
          <div class="tab-panel-shell">
            <GraphSubgraphs
              {graph}
              {subgraphs}
              selectedIndex={selectedSubgraphIndex}
              onSelect={(index) => (selectedSubgraphIndex = index)}
              running={liveRunActive}
              {miningPhase}
              {skipSubgraphsPending}
              onSkipSubgraphs={handleSkipSubgraphs}
            />
          </div>
        {/if}

        <div
          class="qa-panel-host"
          class:hidden-panel={activeTab !== "qa"}
          aria-hidden={activeTab !== "qa"}
        >
          <QaPanel
            {token}
            {endpoint}
            sampleRunId={qaSampleRunId}
            {subgraphs}
            {defaults}
          />
        </div>
      </div>
    </section>
  </main>
{/if}

<style>
  .boot-shell {
    min-height: 100vh;
    display: grid;
    place-items: center;
    background: #f6f7fb;
  }

  .boot-panel {
    border: 1px solid var(--border-default);
    border-radius: 8px;
    background: #fff;
    padding: 16px 20px;
    color: #65708c;
    box-shadow: var(--shadow-md);
  }

  .workbench {
    height: 100vh;
    height: 100dvh;
    display: grid;
    grid-template-columns: 380px minmax(0, 1fr);
    overflow: hidden;
    background: #f6f7fb;
    color: #1c1f2b;
    transition: grid-template-columns 0.18s ease;
  }

  .workbench.rail-collapsed {
    grid-template-columns: 52px minmax(0, 1fr);
  }

  .rail {
    min-height: 0;
    overflow: auto;
    border-right: 1px solid var(--border-default);
    background: #fff;
  }

  .rail.collapsed {
    overflow: hidden;
  }

  .rail > header {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    padding: 16px;
    border-bottom: 1px solid var(--border-default);
  }

  .rail.collapsed > header {
    justify-content: center;
    padding: 12px 8px;
  }

  .brand-block {
    min-width: 0;
  }

  .rail.collapsed .brand-block {
    display: none;
  }

  .rail-actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .rail-toggle {
    width: 30px;
    height: 30px;
    display: inline-grid;
    place-items: center;
    padding: 0;
    font-size: 0.95rem;
    line-height: 1;
  }

  .rail.collapsed .rail-toggle {
    width: 32px;
    height: 32px;
  }

  .collapsed-mark {
    margin-top: 14px;
    color: var(--color-uni-green);
    font-size: 0.72rem;
    font-weight: 900;
    letter-spacing: 0;
    text-align: center;
    writing-mode: vertical-rl;
    transform: rotate(180deg);
    user-select: none;
  }

  h1,
  h2,
  p {
    margin: 0;
  }

  .rail header p {
    color: var(--color-uni-green);
    font-size: 0.74rem;
    font-weight: 900;
    text-transform: uppercase;
  }

  h1 {
    color: var(--color-uni-dark-blue);
    font-size: 1.25rem;
  }

  h2 {
    color: #212a46;
    font-size: 0.95rem;
  }

  button {
    border: 1px solid #d9dfef;
    border-radius: 6px;
    background: #fff;
    color: #2e3d72;
    cursor: pointer;
    font-weight: 800;
  }

  .rail > header button,
  .runs-header button {
    padding: 6px 9px;
  }

  .runs {
    padding: 14px 16px 24px;
  }

  .runs-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 10px;
  }

  .runs article {
    border: 1px solid #e4e8f4;
    border-radius: 7px;
    padding: 9px;
    margin-bottom: 8px;
  }

  .runs article:hover {
    border-color: #b0bce8;
    background: #f7f9ff;
  }

  .runs article.active {
    border-color: rgba(0, 160, 130, 0.55);
  }

  .runs article.run-active {
    border-left: 3px solid #00c896;
  }

  .runs article.restoring {
    opacity: 0.7;
    pointer-events: none;
  }

  .run-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }

  .run-select {
    min-width: 0;
    display: grid;
    gap: 3px;
    padding: 0;
    border: none;
    background: transparent;
    color: inherit;
    text-align: left;
    font: inherit;
  }

  .run-select:hover {
    background: transparent;
  }

  .run-ts {
    font-size: 0.72rem;
    color: #9aa5be;
  }

  .run-status {
    display: flex;
    align-items: center;
    gap: 5px;
  }

  .run-status.is-running::before {
    content: "";
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #00c896;
    flex-shrink: 0;
    animation: pulse-dot 1.4s ease-in-out infinite;
  }

  @keyframes pulse-dot {
    0%,
    100% {
      opacity: 1;
      transform: scale(1);
    }
    50% {
      opacity: 0.3;
      transform: scale(0.6);
    }
  }

  .delete-run {
    flex-shrink: 0;
    background: none;
    border: none;
    padding: 2px 5px;
    border-radius: 4px;
    color: #9aa5be;
    font-size: 0.8rem;
    cursor: pointer;
    line-height: 1;
    opacity: 0;
    transition:
      opacity 0.15s,
      color 0.15s;
  }

  article:hover .delete-run {
    opacity: 1;
  }

  .delete-run:hover {
    color: #e53e3e !important;
  }

  .delete-run:disabled {
    pointer-events: none;
    opacity: 0.4;
  }

  .spinner {
    display: inline-block;
    width: 14px;
    height: 14px;
    border: 2px solid #d0d7ee;
    border-top-color: #3a52b4;
    border-radius: 50%;
    flex-shrink: 0;
    animation: spin 0.7s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .runs span,
  .muted {
    color: #65708c;
    font-size: 0.8rem;
  }

  .main-panel {
    min-width: 0;
    min-height: 0;
    height: 100%;
    overflow: hidden;
    display: grid;
    grid-template-rows: auto auto 1fr;
  }

  .tabs {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px;
    padding: 10px 12px;
    border-bottom: 1px solid var(--border-default);
    background: #fff;
  }

  .tab-sequence {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px;
    min-width: 0;
  }

  .tab-arrow {
    color: #8d99b8;
    font-size: 0.95rem;
    font-weight: 900;
    line-height: 1;
    padding: 0 2px;
  }

  .tabs button {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
  }

  .tab-spinner {
    width: 11px;
    height: 11px;
    border-width: 2px;
  }

  .tabs .logs-tab {
    margin-left: auto;
  }

  .tabs button.active {
    border-color: rgba(52, 74, 154, 0.35);
    background: #edf2ff;
    color: var(--color-uni-blue);
  }

  .tabs .interrupt {
    border-color: rgba(193, 0, 42, 0.22);
    background: rgba(193, 0, 42, 0.08);
    color: var(--color-uni-red);
  }

  .tab-body {
    grid-row: 3;
    min-height: 0;
    height: 100%;
    overflow: hidden;
    background: #fff;
    display: grid;
    grid-template-rows: minmax(0, 1fr);
    align-items: stretch;
  }

  .tab-panel-shell {
    min-width: 0;
    min-height: 0;
    height: 100%;
    display: grid;
    grid-template-rows: minmax(0, 1fr);
    overflow: hidden;
  }

  .qa-panel-host {
    min-height: 0;
    height: 100%;
    display: grid;
    overflow: hidden;
  }

  .hidden-panel {
    display: none;
  }

  .stream-error {
    padding: 8px 12px;
    background: rgba(193, 0, 42, 0.08);
    color: var(--color-uni-red);
    font-size: 0.86rem;
  }

  @media (max-width: 980px) {
    .workbench {
      grid-template-columns: 1fr;
      height: auto;
      min-height: 100vh;
    }

    .tab-sequence {
      width: 100%;
    }

    .tabs .logs-tab {
      margin-left: 0;
    }

    .workbench.rail-collapsed {
      grid-template-columns: 1fr;
    }

    .rail.collapsed {
      min-height: auto;
      border-right: none;
      border-bottom: 1px solid var(--border-default);
    }

    .rail.collapsed > header {
      justify-content: flex-start;
    }

    .collapsed-mark {
      display: none;
    }

    .main-panel {
      min-height: 0;
    }
  }
</style>
