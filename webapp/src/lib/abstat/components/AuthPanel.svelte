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
      <div>
        <span class="brand-name">QueryBloom</span>
        <p class="brand-tagline">KG Subgraph Mining & Text-SPARQL Synthesis</p>
      </div>
    </div>

    <div class="mode-switch" role="tablist" aria-label="Authentication mode">
      <button
        class:active={mode === "login"}
        type="button"
        on:click={() => (mode = "login")}>Log In</button
      >
      <button
        class:active={mode === "signup"}
        type="button"
        on:click={() => (mode = "signup")}>Sign Up</button
      >
    </div>

    <form on:submit|preventDefault={submit}>
      {#if mode === "signup"}
        <label>
          <span>Display Name</span>
          <input
            bind:value={displayName}
            placeholder="Dr. Jane Doe"
            autocomplete="name"
          />
        </label>
      {/if}
      <label>
        <span>Email Address</span>
        <input
          bind:value={email}
          type="email"
          placeholder="researcher@institution.edu"
          autocomplete="email"
          required
        />
      </label>
      <label>
        <span>Password</span>
        <input
          bind:value={password}
          type="password"
          placeholder="••••••••••••"
          autocomplete={mode === "login" ? "current-password" : "new-password"}
          required
        />
      </label>
      {#if error}
        <div class="alert error" role="alert">
          <svg class="alert-icon" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
          </svg>
          <span>{error}</span>
        </div>
      {/if}
      {#if success}
        <div class="alert success" role="status">
          <svg class="alert-icon" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
          </svg>
          <span>{success}</span>
        </div>
      {/if}
      <button class="primary" type="submit" disabled={busy}>
        {#if busy}
          <span class="spinner" aria-hidden="true"></span>
          <span>Processing...</span>
        {:else if mode === "login"}
          <span>Sign In</span>
        {:else}
          <span>Create Account</span>
        {/if}
      </button>
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
    border-radius: 12px;
    background: #fff;
    box-shadow: var(--shadow-md);
    padding: 28px;
    transition: box-shadow 0.2s ease;
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 22px;
  }

  .qb-logo {
    width: 38px;
    height: 38px;
    flex-shrink: 0;
  }

  .brand-name {
    font-size: 1.3rem;
    font-weight: 800;
    color: var(--color-uni-dark-blue);
    letter-spacing: -0.01em;
    display: block;
    line-height: 1.2;
  }

  .brand-tagline {
    font-size: 0.76rem;
    color: var(--text-subtle);
    margin: 2px 0 0 0;
    font-weight: 500;
  }

  .mode-switch {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 4px;
    padding: 4px;
    border: 1px solid #dfe4f2;
    border-radius: 8px;
    background: #f7f8fc;
    margin-bottom: 20px;
  }

  .mode-switch button,
  .primary {
    border: 0;
    border-radius: 6px;
    cursor: pointer;
    font-weight: 700;
    transition: all 0.15s ease;
  }

  .mode-switch button {
    padding: 8px 10px;
    background: transparent;
    color: #5b6380;
    font-size: 0.88rem;
  }

  .mode-switch button:hover {
    color: var(--color-uni-blue);
  }

  .mode-switch button.active {
    background: #fff;
    color: var(--color-uni-blue);
    box-shadow: var(--shadow-xs);
  }

  form,
  label {
    display: grid;
    gap: 14px;
  }

  label {
    gap: 6px;
  }

  label span {
    color: #3b4461;
    font-size: 0.8rem;
    font-weight: 700;
  }

  input {
    width: 100%;
    border: 1px solid #d5dbea;
    border-radius: 6px;
    padding: 10px 12px;
    color: #161b2d;
    font: inherit;
    font-size: 0.92rem;
    background: #fdfdfd;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }

  input::placeholder {
    color: #a0a6b8;
    font-size: 0.88rem;
  }

  input:focus {
    outline: none;
    border-color: var(--color-uni-blue);
    box-shadow: 0 0 0 3px rgba(52, 74, 154, 0.12);
    background: #fff;
  }

  .primary {
    padding: 11px 16px;
    background: var(--color-uni-blue);
    color: #fff;
    font-size: 0.95rem;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    margin-top: 4px;
  }

  .primary:hover:not(:disabled) {
    background: #293b7a;
    box-shadow: var(--shadow-sm);
  }

  .primary:disabled {
    opacity: 0.7;
    cursor: not-allowed;
  }

  .spinner {
    width: 14px;
    height: 14px;
    border: 2px solid rgba(255, 255, 255, 0.3);
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .alert {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 10px 12px;
    border-radius: 6px;
    font-size: 0.84rem;
    line-height: 1.4;
  }

  .alert-icon {
    width: 16px;
    height: 16px;
    flex-shrink: 0;
    margin-top: 2px;
  }

  .alert.error {
    background: #fdf2f4;
    border: 1px solid rgba(193, 0, 42, 0.2);
    color: var(--color-uni-red);
  }

  .alert.success {
    background: #edf7f4;
    border: 1px solid rgba(0, 160, 130, 0.25);
    color: #087a65;
  }
</style>
