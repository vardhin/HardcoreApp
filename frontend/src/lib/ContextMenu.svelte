<!--
  ContextMenu.svelte
  ----------------------------------------------------------------------------
  A website-specific right-click menu. Replaces the browser's native menu with
  an interactive, app-aware one.

  Usage:
    <ContextMenu bind:this={menu} />
    ...
    onContextMenu={(e) => menu.open(e, items)}

  `items` is an array of:
    { label, onSelect, icon?, danger?, disabled?, shortcut? }   - action row
    { separator: true }                                          - divider
    { label, items: [...], icon? }                               - submenu

  The menu closes on selection, outside click, scroll, Escape, or blur.
-->
<script>
	let visible = $state(false);
	let x = $state(0);
	let y = $state(0);
	let items = $state([]);
	let openSubmenu = $state(null);
	let menuEl = $state(null);

	/** Open the menu at the pointer position with the given item list. */
	export function open(event, menuItems) {
		event.preventDefault();
		event.stopPropagation();
		items = menuItems ?? [];
		openSubmenu = null;
		visible = true;
		// Position after render so we can clamp against the real menu size.
		x = event.clientX;
		y = event.clientY;
		queueMicrotask(() => clampToViewport(event.clientX, event.clientY));
	}

	export function close() {
		visible = false;
		openSubmenu = null;
	}

	function clampToViewport(px, py) {
		if (!menuEl) return;
		const rect = menuEl.getBoundingClientRect();
		const pad = 8;
		x = Math.min(px, window.innerWidth - rect.width - pad);
		y = Math.min(py, window.innerHeight - rect.height - pad);
		x = Math.max(pad, x);
		y = Math.max(pad, y);
	}

	function runItem(item) {
		if (item.disabled || item.separator || item.items) return;
		close();
		item.onSelect?.();
	}

	function onKeydown(event) {
		if (event.key === 'Escape') close();
	}
</script>

<svelte:window
	onkeydown={onKeydown}
	onresize={close}
	onblur={close}
/>

{#if visible}
	<!-- Transparent full-screen catcher: any click/contextmenu outside closes. -->
	<div
		class="ctx-overlay"
		role="presentation"
		onpointerdown={close}
		oncontextmenu={(e) => e.preventDefault()}
		onwheel={close}
	></div>

	<div
		class="ctx-menu"
		role="menu"
		tabindex="-1"
		bind:this={menuEl}
		style={`left:${x}px; top:${y}px;`}
		onpointerdown={(e) => e.stopPropagation()}
		oncontextmenu={(e) => e.preventDefault()}
	>
		{#each items as item, i (i)}
			{#if item.separator}
				<div class="ctx-sep" role="separator"></div>
			{:else if item.items}
				<!-- submenu parent -->
				<div
					class="ctx-item has-sub"
					class:open={openSubmenu === i}
					role="menuitem"
					tabindex="-1"
					onpointerenter={() => (openSubmenu = i)}
				>
					{#if item.icon}<span class="ctx-icon">{item.icon}</span>{/if}
					<span class="ctx-label">{item.label}</span>
					<span class="ctx-arrow">›</span>

					{#if openSubmenu === i}
						<div class="ctx-submenu" role="menu">
							{#each item.items as sub, j (j)}
								{#if sub.separator}
									<div class="ctx-sep" role="separator"></div>
								{:else}
									<button
										class="ctx-item"
										class:danger={sub.danger}
										role="menuitem"
										disabled={sub.disabled}
										onclick={() => runItem(sub)}
									>
										{#if sub.icon}<span class="ctx-icon">{sub.icon}</span>{/if}
										<span class="ctx-label">{sub.label}</span>
										{#if sub.shortcut}<span class="ctx-shortcut">{sub.shortcut}</span>{/if}
									</button>
								{/if}
							{/each}
						</div>
					{/if}
				</div>
			{:else}
				<button
					class="ctx-item"
					class:danger={item.danger}
					role="menuitem"
					disabled={item.disabled}
					onpointerenter={() => (openSubmenu = null)}
					onclick={() => runItem(item)}
				>
					{#if item.icon}<span class="ctx-icon">{item.icon}</span>{/if}
					<span class="ctx-label">{item.label}</span>
					{#if item.shortcut}<span class="ctx-shortcut">{item.shortcut}</span>{/if}
				</button>
			{/if}
		{/each}
	</div>
{/if}

<style>
	.ctx-overlay {
		position: fixed;
		inset: 0;
		z-index: 900;
	}

	.ctx-menu {
		position: fixed;
		z-index: 901;
		min-width: 196px;
		padding: 0.3rem;
		background: #1b2129;
		border: 1px solid #38424f;
		border-radius: 9px;
		box-shadow: 0 18px 44px rgb(0 0 0 / 0.55);
		display: flex;
		flex-direction: column;
		gap: 1px;
		animation: ctx-pop 0.09s ease-out;
		font-size: 0.83rem;
	}

	@keyframes ctx-pop {
		from {
			opacity: 0;
			transform: scale(0.97) translateY(-3px);
		}
		to {
			opacity: 1;
			transform: none;
		}
	}

	.ctx-item {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		width: 100%;
		padding: 0.42rem 0.55rem;
		border: none;
		border-radius: 6px;
		background: transparent;
		color: #e7edf4;
		text-align: left;
		cursor: pointer;
		font: inherit;
		position: relative;
	}

	.ctx-item:hover:not(:disabled),
	.ctx-item.open {
		background: #2a3340;
	}

	.ctx-item:disabled {
		color: #5f6b7a;
		cursor: not-allowed;
	}

	.ctx-item.danger {
		color: #ff9aa6;
	}

	.ctx-item.danger:hover:not(:disabled) {
		background: #2e1d22;
	}

	.ctx-icon {
		width: 1.05rem;
		text-align: center;
		flex-shrink: 0;
		font-size: 0.9rem;
	}

	.ctx-label {
		flex: 1;
		white-space: nowrap;
	}

	.ctx-shortcut {
		color: #75808f;
		font-size: 0.72rem;
		letter-spacing: 0.02em;
	}

	.ctx-arrow {
		color: #75808f;
		font-size: 0.95rem;
		line-height: 1;
	}

	.ctx-sep {
		height: 1px;
		margin: 0.22rem 0.3rem;
		background: #333d4a;
	}

	.has-sub {
		cursor: default;
	}

	.ctx-submenu {
		position: absolute;
		left: 100%;
		top: -0.3rem;
		margin-left: 2px;
		min-width: 184px;
		padding: 0.3rem;
		background: #1b2129;
		border: 1px solid #38424f;
		border-radius: 9px;
		box-shadow: 0 18px 44px rgb(0 0 0 / 0.55);
		display: flex;
		flex-direction: column;
		gap: 1px;
		animation: ctx-pop 0.09s ease-out;
	}
</style>
