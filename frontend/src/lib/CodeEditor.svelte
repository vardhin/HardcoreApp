<script>
	import { onDestroy, onMount } from 'svelte';
	import { basicSetup } from 'codemirror';
	import { cpp } from '@codemirror/lang-cpp';
	import { markdown } from '@codemirror/lang-markdown';
	import { EditorState } from '@codemirror/state';
	import { EditorView } from '@codemirror/view';

	let { value = $bindable(''), language = 'c', onchange } = $props();

	let host;
	let view;
	// Guards the update-listener from firing onchange while we are
	// programmatically syncing external value changes into the editor.
	let syncing = false;

	function languageExtension() {
		return language === 'markdown' ? markdown() : cpp();
	}

	function extensions() {
		return [
			basicSetup,
			languageExtension(),
			EditorView.lineWrapping,
			EditorView.updateListener.of((update) => {
				if (update.docChanged && !syncing) {
					value = update.state.doc.toString();
					onchange?.(value);
				}
			}),
			EditorView.theme({
				'&': {
					height: '100%',
					background: '#101317',
					color: '#edf2f7',
					fontSize: '13px'
				},
				'.cm-scroller': {
					fontFamily: 'JetBrains Mono, SFMono-Regular, Consolas, monospace',
					lineHeight: '1.55'
				},
				'.cm-gutters': {
					background: '#0c0f13',
					color: '#758092',
					border: 'none'
				},
				'.cm-activeLineGutter, .cm-activeLine': {
					background: '#19212a'
				},
				'.cm-cursor': {
					borderLeftColor: '#74d7bb'
				},
				'.cm-selectionBackground, &.cm-focused .cm-selectionBackground': {
					background: '#2c3a4a'
				}
			})
		];
	}

	onMount(() => {
		view = new EditorView({
			parent: host,
			state: EditorState.create({
				doc: value,
				extensions: extensions()
			})
		});
	});

	$effect(() => {
		if (!view) return;
		const current = view.state.doc.toString();
		if (value !== current) {
			syncing = true;
			view.dispatch({
				changes: { from: 0, to: current.length, insert: value }
			});
			syncing = false;
		}
	});

	onDestroy(() => {
		view?.destroy();
	});
</script>

<div class="editor" bind:this={host}></div>

<style>
	.editor {
		height: 100%;
		min-height: 0;
		overflow: hidden;
	}
</style>
