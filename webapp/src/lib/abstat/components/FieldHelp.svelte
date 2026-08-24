<script>
    export let description = "";

    let triggerEl;
    let open = false;
    let side = "right";
    let tooltipStyle = "";

    const GAP = 8;
    const VIEWPORT_PADDING = 12;
    const TOOLTIP_WIDTH = 270;

    function updatePosition() {
        if (!triggerEl || typeof window === "undefined") return;
        const rect = triggerEl.getBoundingClientRect();
        const width = Math.min(
            TOOLTIP_WIDTH,
            Math.max(180, window.innerWidth - VIEWPORT_PADDING * 2),
        );
        let left = rect.right + GAP;
        side = "right";

        if (left + width + VIEWPORT_PADDING > window.innerWidth) {
            left = Math.max(VIEWPORT_PADDING, rect.left - width - GAP);
            side = "left";
        }

        const top = Math.min(
            Math.max(rect.top + rect.height / 2, VIEWPORT_PADDING),
            window.innerHeight - VIEWPORT_PADDING,
        );
        tooltipStyle = `left: ${left}px; top: ${top}px; width: ${width}px;`;
    }

    function show() {
        if (!description) return;
        open = true;
        updatePosition();
    }

    function hide() {
        open = false;
    }

    function handleWindowChange() {
        if (open) updatePosition();
    }
</script>

<svelte:window on:resize={handleWindowChange} on:scroll={handleWindowChange} />

<span
    bind:this={triggerEl}
    class="help"
    tabindex="0"
    aria-label={`Field description: ${description}`}
    on:mouseenter={show}
    on:mouseleave={hide}
    on:focus={show}
    on:blur={hide}>?</span
>

{#if open && description}
    <span class="tooltip {side}" style={tooltipStyle} role="tooltip">
        {description}
    </span>
{/if}

<style>
    .help {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 16px;
        height: 16px;
        border: 1px solid #c8d0e4;
        border-radius: 50%;
        background: #fff;
        color: #536083;
        cursor: help;
        flex: 0 0 auto;
        font-size: 0.68rem;
        font-weight: 900;
        line-height: 1;
        text-transform: none;
    }

    .tooltip {
        position: fixed;
        z-index: 10000;
        padding: 8px 9px;
        border: 1px solid #d8deed;
        border-radius: 6px;
        background: #151a2b;
        box-shadow: 0 10px 24px rgba(21, 26, 43, 0.16);
        color: #fff;
        font-size: 0.74rem;
        font-weight: 600;
        letter-spacing: 0;
        line-height: 1.35;
        pointer-events: none;
        text-align: left;
        text-transform: none;
        transform: translateY(-50%);
        white-space: normal;
    }

    .tooltip::before {
        position: absolute;
        top: 50%;
        width: 8px;
        height: 8px;
        background: #151a2b;
        content: "";
        transform: translateY(-50%) rotate(45deg);
    }

    .tooltip.right::before {
        left: -4px;
    }

    .tooltip.left::before {
        right: -4px;
    }

    .help:focus-visible {
        outline: 2px solid color-mix(in srgb, var(--color-uni-blue) 45%, white);
        outline-offset: 2px;
    }
</style>
