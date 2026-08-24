<script>
  import { extractAccessToken, login, signup } from "../api.js";

  export let onAuthenticated = () => {};

  let mode = "login";
  let email = "";
  let password = "";
  let displayName = "";
  let error = "";
  let success = "";
  let busy = false;

  async function submit() {
    error = "";
    success = "";
    busy = true;
    try {
      const session =
        mode === "login"
          ? await login(email, password)
          : await signup(email, password, displayName);
      if (!extractAccessToken(session)) {
        success =
          "Account created. Check your email for the confirmation link, then log in.";
        mode = "login";
        password = "";
        return;
      }
      onAuthenticated(session);
    } catch (err) {
      error = err?.message || "Authentication failed";
    } finally {
      busy = false;
    }
  }
</script>

<section class="auth-shell">
  <div class="auth-panel">
    <div class="brand">
      <svg
        class="qb-logo"
        viewBox="0 0 36 36"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
      >
        <circle cx="14" cy="14" r="10" stroke="#00c896" stroke-width="3" />
        <line
          x1="21"
          y1="21"
          x2="31"
          y2="31"
          stroke="#00c896"
          stroke-width="3"
          stroke-linecap="round"
        />
        <circle cx="14" cy="14" r="4" fill="#00c896" opacity="0.25" />
      </svg>
      <span class="brand-name">QueryBloom</span>
    </div>
    <div></div>

    <div class="mode-switch" role="tablist" aria-label="Authentication mode">
      <button
        class:active={mode === "login"}
        type="button"
        on:click={() => (mode = "login")}>Login</button
      >
      <button
        class:active={mode === "signup"}
        type="button"
        on:click={() => (mode = "signup")}>Sign up</button
      >
    </div>

    <form on:submit|preventDefault={submit}>
      {#if mode === "signup"}
        <label>
          <span>Name</span>
          <input bind:value={displayName} autocomplete="name" />
        </label>
      {/if}
      <label>
        <span>Email</span>
        <input bind:value={email} type="email" autocomplete="email" required />
      </label>
      <label>
        <span>Password</span>
        <input
          bind:value={password}
          type="password"
          autocomplete={mode === "login" ? "current-password" : "new-password"}
          required
        />
      </label>
      {#if error}
        <p class="error">{error}</p>
      {/if}
      {#if success}
        <p class="success">{success}</p>
      {/if}
      <button class="primary" type="submit" disabled={busy}
        >{busy
          ? "Working..."
          : mode === "login"
            ? "Login"
            : "Create account"}</button
      >
    </form>
  </div>
</section>

<style>
  .auth-shell {
    min-height: 100vh;
    display: grid;
    place-items: center;
    padding: 24px;
  }

  .auth-panel {
    width: min(440px, 100%);
    border: 1px solid var(--border-default);
    border-radius: 8px;
    background: #fff;
    box-shadow: var(--shadow-md);
    padding: 24px;
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 20px;
  }

  .qb-logo {
    width: 36px;
    height: 36px;
    flex-shrink: 0;
  }

  .brand-name {
    font-size: 1.25rem;
    font-weight: 800;
    color: var(--color-uni-dark-blue);
    letter-spacing: -0.01em;
  }

  .mode-switch {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 4px;
    padding: 4px;
    border: 1px solid #dfe4f2;
    border-radius: 8px;
    background: #f7f8fc;
    margin-bottom: 18px;
  }

  .mode-switch button,
  .primary {
    border: 0;
    border-radius: 6px;
    cursor: pointer;
    font-weight: 800;
  }

  .mode-switch button {
    padding: 8px 10px;
    background: transparent;
    color: #5b6380;
  }

  .mode-switch button.active {
    background: #fff;
    color: var(--color-uni-blue);
    box-shadow: var(--shadow-xs);
  }

  form,
  label {
    display: grid;
    gap: 12px;
  }

  label span {
    color: #4d5875;
    font-size: 0.78rem;
    font-weight: 800;
  }

  input {
    width: 100%;
    border: 1px solid #d5dbea;
    border-radius: 6px;
    padding: 9px 10px;
    color: #161b2d;
    font: inherit;
  }

  .primary {
    padding: 10px 14px;
    background: var(--color-uni-blue);
    color: #fff;
  }

  .primary:disabled {
    opacity: 0.62;
    cursor: wait;
  }

  .error {
    margin: 0;
    color: var(--color-uni-red);
    font-size: 0.84rem;
  }

  .success {
    margin: 0;
    color: #087a65;
    font-size: 0.84rem;
  }
</style>
