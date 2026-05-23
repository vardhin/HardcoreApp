<script>
	/* AssistantPanel.svelte
	 * -------------------------------------------------------------------------
	 * The AI agent panel, docked on the Workbench and Code pages.
	 *
	 * The user types a hardware problem statement and picks an LLM provider.
	 * "Solve" runs the backend two-phase agent (POST .../agent/solve): phase 1
	 * configures + wires the workbench, phase 2 writes the firmware — each in an
	 * isolated LLM context. The panel streams the THINK / CALL trace of both
	 * phases as the run completes, then calls `ondone` so the parent reloads the
	 * workbench and files from the database.
	 */
	let { projectId, apiBase, token, onstatus, ondone } = $props();

	let problem = $state('');
	let provider = $state('llamacpp');
	let providers = $state([]);
	let running = $state(false);
	let collapsed = $state(false);
	let error = $state('');
	// result: { provider, wiring:{steps,final}, coding:{steps,final} } | null
	let result = $state(null);
	let activePhase = $state('wiring'); // which phase trace tab is shown

	const PHASE_LABEL = { wiring: 'Phase 1 · Wiring', coding: 'Phase 2 · Coding' };

	$effect(() => {
		// Reload the provider list whenever the panel mounts for a project.
		if (projectId) loadProviders();
	});

	async function loadProviders() {
		try {
			const res = await fetch(`${apiBase}/api/agent/providers`);
			if (!res.ok) throw new Error(`providers ${res.status}`);
			const body = await res.json();
			providers = body.providers ?? [];
			// Default to the first available provider.
			const firstUsable = providers.find((p) => p.available);
			if (firstUsable) provider = firstUsable.id;
		} catch {
			// Backend not reachable yet — keep the llamacpp default; Solve will report.
			providers = [];
		}
	}

	function providerLabel(id) {
		return providers.find((p) => p.id === id)?.label ?? id;
	}

	function providerAvailable(id) {
		const p = providers.find((x) => x.id === id);
		return p ? p.available : true;
	}

	async function solve() {
		if (!projectId || running) return;
		if (!problem.trim()) {
			error = 'Describe the hardware problem first.';
			return;
		}
		running = true;
		error = '';
		result = null;
		activePhase = 'wiring';
		onstatus?.('AI agent running — phase 1: wiring…');
		try {
			const headers = { 'Content-Type': 'application/json' };
			if (token) headers['Authorization'] = `Bearer ${token}`;

			const res = await fetch(`${apiBase}/api/projects/${projectId}/agent/solve`, {
				method: 'POST',
				headers,
				body: JSON.stringify({ provider, problem: problem.trim() })
			});
			if (!res.ok) {
				let detail = `Agent failed (${res.status})`;
				try {
					detail = (await res.json()).detail ?? detail;
				} catch {
					/* keep default */
				}
				throw new Error(detail);
			}
			result = await res.json();
			// Land on the coding tab — the firmware is the headline output.
			activePhase = result.coding?.steps?.length ? 'coding' : 'wiring';
			onstatus?.('AI agent finished.');
			ondone?.(result);
		} catch (err) {
			error = err.message;
			onstatus?.('AI agent failed.');
		} finally {
			running = false;
		}
	}

	let shownTrace = $derived(result ? result[activePhase] : null);

	/** Render a tool call's args dict as a C-style argument list. */
	function formatArgs(args) {
		if (!args || typeof args !== 'object') return '';
		return Object.values(args)
			.map((v) => (typeof v === 'string' ? `"${v}"` : String(v)))
			.join(', ');
	}

	/** True when a tool result string reports a failure. */
	function isError(text) {
		return typeof text === 'string' && text.startsWith('ERROR');
	}
</script>

<aside class="assistant" class:collapsed>
	<div class="assistant-head">
		<button
			class="assistant-toggle"
			onclick={() => (collapsed = !collapsed)}
			title={collapsed ? 'Expand AI panel' : 'Collapse AI panel'}
			aria-label="Toggle AI panel"
		>
			<span class="ai-dot" aria-hidden="true"></span>
			<span class="assistant-title">AI Agent</span>
			<span class="fold" class:closed={collapsed}>▾</span>
		</button>
	</div>

	{#if !collapsed}
		<div class="assistant-body">
			<label class="field">
				Problem statement
				<textarea
					rows="4"
					bind:value={problem}
					disabled={running}
					placeholder="e.g. Blink an LED on the STM32, then drive a DC motor through the L298N at half speed."
				></textarea>
			</label>

			<label class="field">
				LLM provider
				<select bind:value={provider} disabled={running}>
					{#each providers as p (p.id)}
						<option value={p.id} disabled={!p.available}>
							{p.label}{p.available ? '' : ' — no key'}
						</option>
					{:else}
						<option value="llamacpp">llama.cpp (Prism Bonsai 8B)</option>
						<option value="openrouter">OpenRouter (gpt-oss-120b)</option>
						<option value="gemini">Gemini 2.5 Flash</option>
					{/each}
				</select>
			</label>

			{#if !providerAvailable(provider)}
				<p class="hint warn">
					{providerLabel(provider)} has no API key. Add it to <code>backend/.env</code>.
				</p>
			{/if}

			<button class="solve" onclick={solve} disabled={running || !projectId}>
				{running ? 'Solving…' : 'Solve — wire it, then code it'}
			</button>

			<p class="hint">
				Runs two isolated agents: one configures and wires the workbench, then a
				fresh one writes <code>src/main.c</code> from the netlist.
			</p>

			{#if error}
				<p class="hint err">{error}</p>
			{/if}

			{#if result}
				<div class="trace">
					<div class="phase-tabs">
						{#each ['wiring', 'coding'] as ph}
							<button
								class:active={activePhase === ph}
								onclick={() => (activePhase = ph)}
							>
								{PHASE_LABEL[ph]}
								<span class="step-count">{result[ph]?.steps?.length ?? 0}</span>
							</button>
						{/each}
					</div>

					<div class="trace-log">
						{#if shownTrace?.steps?.length}
							{#each shownTrace.steps as s (s.step + '-' + (s.call ?? s.note))}
								{#if s.note}
									<div class="trace-note">{s.note}</div>
								{:else}
									<div class="trace-step">
										<div class="think">
											<span class="tag think-tag">THINK</span>
											{s.think || '(no thought)'}
										</div>
										<div class="call">
											<span class="tag call-tag">CALL</span>
											<code>{s.call}({formatArgs(s.args)})</code>
										</div>
										<div class="result" class:bad={isError(s.result)}>
											{s.result}
										</div>
									</div>
								{/if}
							{/each}
						{:else}
							<p class="hint">No tool calls in this phase.</p>
						{/if}

						{#if shownTrace?.final}
							<div class="trace-final">
								<span class="tag final-tag">DONE</span>
								{shownTrace.final}
							</div>
						{/if}
					</div>
				</div>
			{/if}
		</div>
	{/if}
</aside>

<style>
	.assistant {
		display: flex;
		flex-direction: column;
		background: #11151b;
		border: 1px solid #2b333d;
		border-radius: 10px;
		min-height: 0;
		overflow: hidden;
	}

	.assistant.collapsed {
		/* When folded the panel shrinks to just its header bar. */
		align-self: start;
	}

	.assistant-head {
		border-bottom: 1px solid #2b333d;
	}

	.assistant.collapsed .assistant-head {
		border-bottom: none;
	}

	.assistant-toggle {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		width: 100%;
		border: none;
		background: transparent;
		border-radius: 0;
		padding: 0.7rem 0.85rem;
		font-weight: 700;
		font-size: 0.9rem;
	}

	.assistant-toggle:hover:not(:disabled) {
		background: #161b22;
	}

	.ai-dot {
		width: 12px;
		height: 12px;
		border-radius: 50%;
		background: linear-gradient(135deg, #a78bfa, #6d4fd8);
		box-shadow: 0 0 10px rgb(167 139 250 / 0.55);
		flex-shrink: 0;
	}

	.assistant-title {
		flex: 1;
		text-align: left;
	}

	.fold {
		transition: transform 0.15s ease;
		color: #8e9aaa;
	}

	.fold.closed {
		transform: rotate(-90deg);
	}

	.assistant-body {
		display: flex;
		flex-direction: column;
		gap: 0.7rem;
		padding: 0.85rem;
		overflow-y: auto;
		min-height: 0;
	}

	.field {
		display: grid;
		gap: 0.35rem;
		color: #aeb8c6;
		font-size: 0.8rem;
	}

	textarea,
	select {
		width: 100%;
		border: 1px solid #343c46;
		background: #0d1014;
		color: #eef3f8;
		border-radius: 7px;
		padding: 0.55rem 0.6rem;
		font: inherit;
	}

	textarea {
		resize: vertical;
	}

	textarea:focus,
	select:focus {
		outline: none;
		border-color: #a78bfa;
	}

	.solve {
		border: 1px solid #6d4fd8;
		background: #4a37a8;
		color: #f0ecff;
		border-radius: 7px;
		padding: 0.6rem 0.8rem;
		font-weight: 700;
		cursor: pointer;
		transition: background 0.12s ease;
	}

	.solve:hover:not(:disabled) {
		background: #5a45c4;
	}

	.solve:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}

	.hint {
		color: #8e9aaa;
		font-size: 0.74rem;
		margin: 0;
		line-height: 1.45;
	}

	.hint.warn {
		color: #f5b95c;
	}

	.hint.err,
	.result.bad {
		color: #ff9aa6;
	}

	code {
		background: #0d1014;
		padding: 0.08rem 0.28rem;
		border-radius: 4px;
		font-size: 0.85em;
		word-break: break-word;
	}

	/* ---- trace ---- */
	.trace {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		border-top: 1px solid #2b333d;
		padding-top: 0.7rem;
	}

	.phase-tabs {
		display: flex;
		gap: 0.35rem;
	}

	.phase-tabs button {
		flex: 1;
		border: 1px solid #2b333d;
		background: #0d1014;
		color: #aeb8c6;
		border-radius: 7px;
		padding: 0.4rem 0.5rem;
		font-size: 0.74rem;
		font-weight: 600;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.35rem;
	}

	.phase-tabs button.active {
		border-color: #6d4fd8;
		background: #241d40;
		color: #d6cdfb;
	}

	.step-count {
		background: #2b333d;
		border-radius: 999px;
		padding: 0 0.4rem;
		font-size: 0.68rem;
	}

	.trace-log {
		display: flex;
		flex-direction: column;
		gap: 0.45rem;
		max-height: 320px;
		overflow-y: auto;
	}

	.trace-step {
		display: grid;
		gap: 0.25rem;
		border: 1px solid #232a33;
		border-radius: 7px;
		padding: 0.45rem 0.55rem;
		background: #0d1014;
		font-size: 0.76rem;
	}

	.tag {
		display: inline-block;
		font-size: 0.62rem;
		font-weight: 800;
		letter-spacing: 0.05em;
		padding: 0.04rem 0.32rem;
		border-radius: 4px;
		margin-right: 0.35rem;
		vertical-align: 1px;
	}

	.think-tag {
		background: #2a2440;
		color: #b9a7f5;
	}

	.call-tag {
		background: #16332c;
		color: #74d7bb;
	}

	.final-tag {
		background: #1f7a65;
		color: #eafff8;
	}

	.think {
		color: #c9d3df;
	}

	.call {
		color: #8e9aaa;
	}

	.result {
		color: #7f8b9b;
		font-size: 0.72rem;
		padding-left: 0.2rem;
		border-left: 2px solid #232a33;
		margin-left: 0.1rem;
	}

	.trace-note {
		color: #f5b95c;
		font-size: 0.74rem;
		font-style: italic;
	}

	.trace-final {
		border: 1px solid #2f6b5c;
		background: #16261f;
		border-radius: 7px;
		padding: 0.5rem 0.6rem;
		font-size: 0.78rem;
		color: #c9e8de;
		line-height: 1.45;
	}
</style>
