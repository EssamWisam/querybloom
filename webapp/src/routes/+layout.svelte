<script>
  import "../app.css";
  import "highlight.js/styles/github.css";
  import { onMount } from "svelte";
  import { base } from "$app/paths";

  onMount(() => {
    function report(message, stack, context = {}) {
      try {
        const body = JSON.stringify({
          message: String(message),
          stack: String(stack || ""),
          url: window.location.href,
          context,
        });
        const targetUrl = (base || "") + "/api/v1/client-logs";
        if (navigator.sendBeacon) {
          navigator.sendBeacon(targetUrl, body);
        } else {
          fetch(targetUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body,
          }).catch(() => {});
        }
      } catch {}
    }

    const errorHandler = (event) => {
      report(event.message, event.error?.stack, { file: event.filename, line: event.lineno });
    };
    const rejectionHandler = (event) => {
      report(event.reason?.message || "Unhandled Promise Rejection", event.reason?.stack);
    };

    window.addEventListener("error", errorHandler);
    window.addEventListener("unhandledrejection", rejectionHandler);

    return () => {
      window.removeEventListener("error", errorHandler);
      window.removeEventListener("unhandledrejection", rejectionHandler);
    };
  });
</script>

<slot />
