<script module>
  export function sameSnapshot(left, right) {
    return (
      (left?.question ?? "") === (right?.question ?? "") &&
      (left?.sparql ?? "") === (right?.sparql ?? "")
    );
  }

  export function pairEvolutionStages(pair) {
    if (!pair) return [];
    const stages = [];
    const stageOutputs = pair.stage_outputs ?? {};

    const generated = {
      label: "Generate",
      agent: "Generator",
      question: pair.original_question ?? pair.question ?? "",
      sparql: pair.original_sparql_query ?? pair.sparql_query ?? "",
      note: null,
      output: stageOutputs.generate ?? null,
    };
    stages.push(generated);

    if (
      pair.pre_verify_question ||
      pair.pre_verify_sparql_query ||
      pair.complexity_types?.length ||
      stageOutputs.complexity
    ) {
      const complexity = {
        label: "Complexity",
        agent: "Complexity agent",
        question: pair.pre_verify_question ?? pair.question ?? "",
        sparql: pair.pre_verify_sparql_query ?? pair.sparql_query ?? "",
        note: pair.complexity_types?.length
          ? `Added ${pair.complexity_types.join(", ")}`
          : null,
        output: stageOutputs.complexity ?? null,
      };
      if (
        !sameSnapshot(complexity, generated) ||
        complexity.note ||
        complexity.output
      )
        stages.push(complexity);
    }

    if (
      pair.verification_status ||
      pair.verification_reason ||
      pair.pre_reword_question ||
      stageOutputs.verify
    ) {
      const verified = {
        label: "Verify",
        agent: "Verifier",
        question: pair.pre_reword_question ?? pair.question ?? "",
        sparql: pair.sparql_query ?? pair.pre_verify_sparql_query ?? "",
        note:
          pair.verification_reason ||
          (pair.verification_status
            ? `Status: ${pair.verification_status}`
            : null),
        output: stageOutputs.verify ?? null,
      };
      if (
        !sameSnapshot(verified, stages[stages.length - 1]) ||
        verified.note ||
        verified.output
      )
        stages.push(verified);
    }

    const finalStage = {
      label:
        pair.pre_reword_question || pair.reword_reason ? "Reword" : "Final",
      agent:
        pair.pre_reword_question || pair.reword_reason
          ? "Reword agent"
          : "Stored result",
      question: pair.question ?? "",
      sparql: pair.sparql_query ?? "",
      note: pair.reword_reason || null,
      output: stageOutputs.reword ?? null,
    };
    if (
      !sameSnapshot(finalStage, stages[stages.length - 1]) ||
      finalStage.note ||
      finalStage.output ||
      stages.length === 1
    ) {
      stages.push(finalStage);
    }

    return stages;
  }
</script>

<script>
  import hljs from "highlight.js";
  import StructuredOutputViewer from "./StructuredOutputViewer.svelte";

  export let pair;

  let activeModalStage = null;
  let activeOutputModalStage = null;
  let copied = false;
  let copyTimeout = null;

  function highlightSparql(query) {
    if (!query) return "";
    try {
      return hljs.highlight(query, { language: "sql", ignoreIllegals: true })
        .value;
    } catch {
      return hljs.highlightAuto(query).value;
    }
  }

  function openSparqlModal(stage) {
    activeModalStage = stage;
    copied = false;
  }

  function closeSparqlModal() {
    activeModalStage = null;
    copied = false;
    if (copyTimeout) clearTimeout(copyTimeout);
  }

  function openOutputModal(stage) {
    activeOutputModalStage = stage;
  }

  function closeOutputModal() {
    activeOutputModalStage = null;
  }

  function copySparql(query) {
    if (!query) return;
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(query);
      copied = true;
      if (copyTimeout) clearTimeout(copyTimeout);
      copyTimeout = setTimeout(() => {
        copied = false;
      }, 2000);
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Escape") {
      if (activeOutputModalStage) closeOutputModal();
      if (activeModalStage) closeSparqlModal();
    }
  }

  $: stages = pairEvolutionStages(pair);
</script>

<svelte:window on:keydown={handleKeyDown} />

<div class="qa-body qa-evolution-body">
  <div class="qa-section">
    <span class="section-label">Evolution</span>
    <ol class="evolution-list">
      {#each stages as stage, stageIndex}
        <li class="evolution-step">
          <div class="evolution-head">
            <div>
              <strong>{stageIndex + 1}. {stage.label}</strong>
              <span class="muted evolution-agent">{stage.agent}</span>
            </div>
            <div class="evolution-head-actions">
              {#if stage.note}
                <span class="badge badge-neutral">note</span>
              {/if}
              {#if stage.output}
                <button
                  type="button"
                  class="evolution-output-btn"
                  on:click={() => openOutputModal(stage)}
                >
                  Show Output
                </button>
              {/if}
              {#if stage.sparql}
                <button
                  type="button"
                  class="evolution-sparql-btn"
                  on:click={() => openSparqlModal(stage)}
                >
                  Show SPARQL
                </button>
              {/if}
            </div>
          </div>
          {#if stage.note}
            <p class="evolution-note">{stage.note}</p>
          {/if}
          <p class="evolution-text">
            {stage.question || "—"}
          </p>
        </li>
      {/each}
    </ol>
  </div>
</div>

{#if activeOutputModalStage}
  <div
    class="modal-backdrop"
    role="presentation"
    on:click|self={closeOutputModal}
  >
    <div
      class="modal-card output-modal-card"
      role="dialog"
      aria-modal="true"
      aria-labelledby="output-modal-title"
    >
      <div class="modal-header">
        <div class="modal-title-wrap">
          <span class="modal-icon" aria-hidden="true">📦</span>
          <div>
            <h3 id="output-modal-title">Stage Structured Output</h3>
            <span class="modal-subtitle">
              Stage: <strong>{activeOutputModalStage.label}</strong> ({activeOutputModalStage.agent})
            </span>
          </div>
        </div>
        <button
          type="button"
          class="modal-close-btn"
          aria-label="Close"
          on:click={closeOutputModal}
        >✕</button>
      </div>

      <div class="modal-body">
        <StructuredOutputViewer data={activeOutputModalStage.output} />
      </div>

      <div class="modal-actions">
        <button
          type="button"
          class="modal-close-action-btn"
          on:click={closeOutputModal}
        >
          Close
        </button>
      </div>
    </div>
  </div>
{/if}

{#if activeModalStage}
  <div
    class="modal-backdrop"
    role="presentation"
    on:click|self={closeSparqlModal}
  >
    <div
      class="modal-card sparql-modal-card"
      role="dialog"
      aria-modal="true"
      aria-labelledby="sparql-modal-title"
    >
      <div class="modal-header">
        <div class="modal-title-wrap">
          <span class="modal-icon" aria-hidden="true">⚡</span>
          <div>
            <h3 id="sparql-modal-title">SPARQL Query</h3>
            <span class="modal-subtitle">
              Stage: <strong>{activeModalStage.label}</strong> ({activeModalStage.agent})
            </span>
          </div>
        </div>
        <button
          type="button"
          class="modal-close-btn"
          aria-label="Close"
          on:click={closeSparqlModal}
        >✕</button>
      </div>

      <div class="modal-body">
        {#if activeModalStage.question}
          <div class="modal-section">
            <span class="evolution-label">Question</span>
            <p class="modal-question-text">{activeModalStage.question}</p>
          </div>
        {/if}

        <div class="modal-section">
          <div class="sparql-header-row">
            <span class="evolution-label">SPARQL Query</span>
            <button
              type="button"
              class="copy-sparql-btn"
              on:click={() => copySparql(activeModalStage.sparql)}
            >
              {copied ? "✓ Copied" : "Copy Query"}
            </button>
          </div>
          <pre class="sparql modal-sparql"><code class="hljs language-sql"
              >{@html highlightSparql(activeModalStage.sparql)}</code
            ></pre>
        </div>
      </div>

      <div class="modal-actions">
        <button
          type="button"
          class="modal-close-action-btn"
          on:click={closeSparqlModal}
        >
          Close
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .qa-body {
    display: grid;
    gap: 14px;
  }

  .qa-section {
    display: grid;
    gap: 8px;
  }

  .section-label,
  .evolution-label {
    color: #66708a;
    font-size: 0.74rem;
    font-weight: 800;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .evolution-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 12px;
  }

  .evolution-step {
    border: 1px solid #e4e8f4;
    border-radius: 8px;
    background: #f9fafd;
    padding: 12px;
    display: grid;
    gap: 10px;
  }

  .evolution-head {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    align-items: center;
  }

  .evolution-head-actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .evolution-output-btn {
    display: inline-flex;
    align-items: center;
    padding: 4px 10px;
    font-size: 0.76rem;
    font-weight: 600;
    color: #475569;
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .evolution-output-btn:hover {
    background: #f1f5f9;
    border-color: #94a3b8;
    color: #0f172a;
  }

  .output-modal-card {
    max-width: 740px;
  }

  .evolution-sparql-btn {
    display: inline-flex;
    align-items: center;
    padding: 4px 10px;
    font-size: 0.76rem;
    font-weight: 600;
    color: #2563eb;
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 5px;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .evolution-sparql-btn:hover {
    background: #dbeafe;
    border-color: #93c5fd;
    color: #1d4ed8;
  }

  .evolution-agent {
    display: block;
    margin-top: 2px;
  }

  .evolution-note {
    margin: 0;
    color: #475569;
    font-size: 0.82rem;
    background: #f1f5f9;
    padding: 6px 10px;
    border-radius: 6px;
    border-left: 3px solid #94a3b8;
  }

  .evolution-text {
    margin: 0;
    color: #1e293b;
    font-size: 0.95rem;
    font-weight: 600;
    line-height: 1.5;
  }

  .badge {
    border-radius: 4px;
    padding: 2px 7px;
    font-size: 0.72rem;
    font-weight: 600;
  }

  .badge-neutral {
    background: #f0f2f7;
    color: #4b5675;
  }

  .muted {
    color: #707b97;
    font-size: 0.8rem;
  }

  .sparql {
    margin: 0;
    border-radius: 6px;
    background: #f4f6fb;
    padding: 10px 11px;
    overflow-x: auto;
  }

  .sparql code {
    font-size: 0.78rem;
    white-space: pre;
  }

  /* ── Modal / Popup ───────────────────────────────────── */
  .modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: 9999;
    background: rgba(15, 23, 42, 0.6);
    backdrop-filter: blur(4px);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
  }

  .modal-card {
    background: #ffffff;
    border-radius: 12px;
    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2), 0 10px 10px -5px rgba(0, 0, 0, 0.1);
    border: 1px solid #e2e8f0;
    max-width: 680px;
    width: 100%;
    max-height: 85vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    animation: modalPop 0.18s cubic-bezier(0.16, 1, 0.3, 1);
  }

  @keyframes modalPop {
    from {
      opacity: 0;
      transform: scale(0.96) translateY(6px);
    }
    to {
      opacity: 1;
      transform: scale(1) translateY(0);
    }
  }

  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 20px;
    background: #f8fafc;
    border-bottom: 1px solid #e2e8f0;
  }

  .modal-title-wrap {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .modal-icon {
    font-size: 1.25rem;
  }

  .modal-header h3 {
    margin: 0;
    font-size: 1rem;
    font-weight: 700;
    color: #1e293b;
  }

  .modal-subtitle {
    font-size: 0.78rem;
    color: #64748b;
  }

  .modal-close-btn {
    background: transparent;
    border: none;
    font-size: 1.15rem;
    color: #94a3b8;
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 4px;
    line-height: 1;
    transition: color 0.15s, background 0.15s;
  }

  .modal-close-btn:hover {
    color: #1e293b;
    background: #e2e8f0;
  }

  .modal-body {
    padding: 18px 20px;
    overflow-y: auto;
    display: grid;
    gap: 16px;
  }

  .modal-section {
    display: grid;
    gap: 6px;
  }

  .modal-question-text {
    margin: 0;
    color: #1e293b;
    font-size: 0.88rem;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 10px 12px;
    line-height: 1.45;
  }

  .sparql-header-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .copy-sparql-btn {
    padding: 3px 9px;
    font-size: 0.74rem;
    font-weight: 600;
    color: #475569;
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .copy-sparql-btn:hover {
    background: #e2e8f0;
    color: #1e293b;
  }

  .modal-sparql {
    max-height: 340px;
    overflow: auto;
    border: 1px solid #e2e8f0;
  }

  .modal-actions {
    padding: 12px 20px;
    background: #f8fafc;
    border-top: 1px solid #e2e8f0;
    display: flex;
    justify-content: flex-end;
  }

  .modal-close-action-btn {
    background: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 7px 18px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s ease;
  }

  .modal-close-action-btn:hover {
    background: #1d4ed8;
  }
</style>
