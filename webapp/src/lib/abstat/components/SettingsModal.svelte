<script>
    export let open = false;
    export let title = "Advanced settings";
    export let titleId = "settings-modal-title";
    /** @type {() => void} */
    export let onClose = () => {};

    function handleKeydown(event) {
        if (event.key === "Escape") onClose();
    }
</script>

{#if open}
    <div
        class="modal-backdrop"
        role="presentation"
        on:click={onClose}
        on:keydown={handleKeydown}
    >
        <div
            class="modal-card"
            role="dialog"
            tabindex="-1"
            aria-modal="true"
            aria-labelledby={titleId}
            on:click|stopPropagation
            on:keydown|stopPropagation
        >
            <div class="modal-header">
                <div class="modal-title-wrap">
                    <h3 id={titleId}>{title}</h3>
                </div>
                <button
                    class="modal-close-btn"
                    type="button"
                    aria-label="Close"
                    on:click={onClose}>✕</button
                >
            </div>
            <div class="modal-body">
                <slot />
            </div>
            <div class="modal-actions">
                <slot name="actions">
                    <button
                        class="modal-primary-btn"
                        type="button"
                        on:click={onClose}>Done</button
                    >
                </slot>
            </div>
        </div>
    </div>
{/if}

<style>
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
        border: 0;
        border-radius: 6px;
        padding: 8px 12px;
        background: var(--color-uni-blue);
        color: #fff;
        cursor: pointer;
        font-weight: 800;
    }

    .modal-body :global(.advanced-section) {
        display: grid;
        gap: 10px;
    }

    .modal-body :global(.advanced-section h4) {
        margin: 0;
        color: var(--color-uni-dark-blue);
        font-size: 0.78rem;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .modal-body :global(.advanced) {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
    }

    .modal-body :global(.full) {
        grid-column: 1 / -1;
    }

    .modal-body :global(.toggle-row) {
        align-content: start;
    }

    .modal-body :global(.toggle-row input) {
        width: auto;
        justify-self: start;
        accent-color: var(--color-uni-green);
    }

    @media (max-width: 920px) {
        .modal-body :global(.advanced) {
            grid-template-columns: 1fr;
        }
    }
</style>
