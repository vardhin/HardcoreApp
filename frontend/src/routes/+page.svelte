<script>
	import { onMount } from 'svelte';
	import { fade, fly } from 'svelte/transition';
	import CodeEditor from '$lib/CodeEditor.svelte';
	import ContextMenu from '$lib/ContextMenu.svelte';

	const API_BASE = 'http://127.0.0.1:8000';
	const wireColors = ['#52d1a4', '#f59e0b', '#60a5fa', '#f472b6', '#f87171', '#a78bfa'];
	const GRID = 12;
	const CANVAS_W = 1600;
	const CANVAS_H = 1000;

	let projects = $state([]);
	let components = $state([]);
	let files = $state([]);
	let workbench = $state({ placed_components: [], wires: [], viewport: { x: 0, y: 0, zoom: 1 } });
	let selectedProject = $state(null);
	let selectedComponentId = $state(null);
	let selectedWireId = $state(null);
	let activeFilePath = $state('');
	let activeView = $state('dashboard');
	let componentSearch = $state('');
	let projectName = $state('Motor Controller');
	let projectDescription = $state('STM32 Blue Pill hardware prototype');
	let pendingPin = $state(null);
	let saveStatus = $state('Ready');
	let loading = $state(true);
	let moving = $state(null);
	let toasts = $state([]);
	let workbenchDirty = $state(false);
	let fileDirty = $state(false);
	let renamingProjectId = $state(null);
	let renameDraft = $state('');
	let busy = $state(false);

	let contextMenu = $state(null);
	let clipboard = $state(null); // a copied placed-component instance
	let lastCanvasPoint = $state({ x: 480, y: 280 });

	let saveTimer;
	let toastSeq = 0;

	let filteredComponents = $derived(
		components.filter((component) => {
			const term = componentSearch.trim().toLowerCase();
			if (!term) return true;
			return [component.name, component.category, component.description].some((value) =>
				value.toLowerCase().includes(term)
			);
		})
	);

	let selectedComponent = $derived(
		workbench.placed_components.find((item) => item.id === selectedComponentId)
	);
	let activeFile = $derived(files.find((file) => file.path === activeFilePath));
	let selectedWire = $derived(workbench.wires.find((wire) => wire.id === selectedWireId));

	onMount(async () => {
		await Promise.all([loadComponents(), loadProjects()]);
		loading = false;
		window.addEventListener('keydown', handleGlobalKey);
		window.addEventListener('beforeunload', warnUnsaved);
		return () => {
			window.removeEventListener('keydown', handleGlobalKey);
			window.removeEventListener('beforeunload', warnUnsaved);
		};
	});

	function warnUnsaved(event) {
		if (workbenchDirty || fileDirty) {
			event.preventDefault();
			event.returnValue = '';
		}
	}

	function handleGlobalKey(event) {
		const inField = ['INPUT', 'TEXTAREA'].includes(event.target?.tagName);
		const mod = event.ctrlKey || event.metaKey;
		if (activeView === 'workbench' && !inField) {
			if ((event.key === 'Delete' || event.key === 'Backspace') && (selectedComponentId || selectedWireId)) {
				event.preventDefault();
				deleteSelected();
			}
			if (event.key === 'Escape') {
				selectedComponentId = null;
				selectedWireId = null;
				pendingPin = null;
				contextMenu?.close();
			}
			if (event.key === 'r' && !mod && selectedComponentId) {
				event.preventDefault();
				rotateSelected();
			}
			if (mod && event.key === 'd' && selectedComponent) {
				event.preventDefault();
				duplicateComponent(selectedComponent);
			}
			if (mod && event.key === 'c' && selectedComponent) {
				event.preventDefault();
				copyComponent(selectedComponent);
			}
			if (mod && event.key === 'v' && clipboard) {
				event.preventDefault();
				pasteComponent();
			}
		}
		if (mod && event.key === 's') {
			event.preventDefault();
			if (activeView === 'workbench' && selectedProject) saveWorkbench();
			else if (activeView === 'code' && activeFile) saveActiveFile();
		}
	}

	function toast(message, kind = 'info') {
		const id = ++toastSeq;
		toasts = [...toasts, { id, message, kind }];
		setTimeout(() => {
			toasts = toasts.filter((item) => item.id !== id);
		}, kind === 'error' ? 6000 : 3500);
	}

	function setStatus(text, sticky = false) {
		saveStatus = text;
		clearTimeout(saveTimer);
		if (!sticky) {
			saveTimer = setTimeout(() => {
				saveStatus = workbenchDirty || fileDirty ? 'Unsaved changes' : 'Ready';
			}, 4000);
		}
	}

	async function api(path, options = {}) {
		const response = await fetch(`${API_BASE}${path}`, {
			headers: { 'Content-Type': 'application/json', ...(options.headers ?? {}) },
			...options
		});
		if (!response.ok) {
			let detail = `Request failed (${response.status})`;
			try {
				const body = await response.json();
				detail = body.detail ?? detail;
			} catch {
				/* keep default */
			}
			throw new Error(detail);
		}
		if (response.status === 204) return null;
		return response.json();
	}

	async function loadComponents() {
		try {
			components = await api('/api/components');
		} catch (error) {
			toast(`Could not load components: ${error.message}`, 'error');
		}
	}

	async function loadProjects() {
		try {
			projects = await api('/api/projects');
			if (!selectedProject && projects.length) {
				await openProject(projects[0]);
			}
		} catch (error) {
			toast(`Cannot reach the API. Start FastAPI on port 8000. ${error.message}`, 'error');
		}
	}

	async function createProject() {
		const name = projectName.trim();
		if (!name) {
			toast('Project name is required.', 'error');
			return;
		}
		busy = true;
		try {
			const project = await api('/api/projects', {
				method: 'POST',
				body: JSON.stringify({ name, description: projectDescription.trim() })
			});
			projects = [project, ...projects];
			projectName = 'Motor Controller';
			projectDescription = 'STM32 Blue Pill hardware prototype';
			await openProject(project);
			toast(`Created "${project.name}".`, 'success');
		} catch (error) {
			toast(`Could not create project: ${error.message}`, 'error');
		} finally {
			busy = false;
		}
	}

	async function deleteProject(project) {
		if (!confirm(`Delete "${project.name}"? This removes its workbench and files.`)) return;
		try {
			await api(`/api/projects/${project.id}`, { method: 'DELETE' });
			projects = projects.filter((item) => item.id !== project.id);
			if (selectedProject?.id === project.id) {
				selectedProject = null;
				workbench = { placed_components: [], wires: [], viewport: { x: 0, y: 0, zoom: 1 } };
				files = [];
				activeView = 'dashboard';
				workbenchDirty = false;
				fileDirty = false;
			}
			toast(`Deleted "${project.name}".`, 'success');
		} catch (error) {
			toast(`Could not delete project: ${error.message}`, 'error');
		}
	}

	function startRename(project) {
		renamingProjectId = project.id;
		renameDraft = project.name;
	}

	async function commitRename(project) {
		const name = renameDraft.trim();
		renamingProjectId = null;
		if (!name || name === project.name) return;
		try {
			const updated = await api(`/api/projects/${project.id}`, {
				method: 'PATCH',
				body: JSON.stringify({ name })
			});
			projects = projects.map((item) => (item.id === updated.id ? updated : item));
			if (selectedProject?.id === updated.id) selectedProject = updated;
			toast('Project renamed.', 'success');
		} catch (error) {
			toast(`Rename failed: ${error.message}`, 'error');
		}
	}

	async function openProject(project) {
		if ((workbenchDirty || fileDirty) && selectedProject?.id !== project.id) {
			if (!confirm('You have unsaved changes. Open another project anyway?')) return;
		}
		selectedProject = project;
		selectedComponentId = null;
		selectedWireId = null;
		pendingPin = null;
		try {
			await Promise.all([loadWorkbench(project.id), loadFiles(project.id)]);
			workbenchDirty = false;
			fileDirty = false;
			activeView = 'workbench';
		} catch (error) {
			toast(`Could not open project: ${error.message}`, 'error');
		}
	}

	async function loadWorkbench(projectId) {
		const data = await api(`/api/projects/${projectId}/workbench`);
		workbench = {
			placed_components: data.placed_components ?? [],
			wires: data.wires ?? [],
			viewport: data.viewport ?? { x: 0, y: 0, zoom: 1 }
		};
	}

	async function loadFiles(projectId) {
		files = await api(`/api/projects/${projectId}/files`);
		activeFilePath = files[0]?.path ?? '';
	}

	async function saveWorkbench() {
		if (!selectedProject) return;
		setStatus('Saving workbench...', true);
		try {
			const saved = await api(`/api/projects/${selectedProject.id}/workbench`, {
				method: 'PUT',
				body: JSON.stringify(workbench)
			});
			workbench = {
				placed_components: saved.placed_components ?? [],
				wires: saved.wires ?? [],
				viewport: saved.viewport ?? workbench.viewport
			};
			workbenchDirty = false;
			setStatus(`Workbench saved ${new Date().toLocaleTimeString()}`);
			touchProjectTimestamp();
		} catch (error) {
			setStatus('Save failed');
			toast(error.message, 'error');
		}
	}

	async function saveActiveFile() {
		if (!selectedProject || !activeFile) return;
		setStatus('Saving file...', true);
		try {
			const saved = await api(
				`/api/projects/${selectedProject.id}/files/${activeFile.path}`,
				{
					method: 'PUT',
					body: JSON.stringify({ language: activeFile.language, content: activeFile.content })
				}
			);
			files = files.map((file) => (file.path === saved.path ? saved : file));
			fileDirty = false;
			setStatus(`Saved ${saved.path}`);
			touchProjectTimestamp();
		} catch (error) {
			setStatus('File save failed');
			toast(error.message, 'error');
		}
	}

	async function generateFirmware() {
		if (!selectedProject) return;
		if (workbenchDirty) await saveWorkbench();
		busy = true;
		setStatus('Generating firmware...', true);
		try {
			const result = await api(`/api/projects/${selectedProject.id}/generate`, {
				method: 'POST'
			});
			await loadFiles(selectedProject.id);
			activeFilePath = result.path;
			activeView = 'code';
			fileDirty = false;
			setStatus(`Generated ${result.path}`);
			toast(`Firmware generated - ${result.summary}`, 'success');
			for (const warning of result.warnings ?? []) toast(warning, 'warn');
		} catch (error) {
			setStatus('Generation failed');
			toast(error.message, 'error');
		} finally {
			busy = false;
		}
	}

	function touchProjectTimestamp() {
		if (!selectedProject) return;
		const stamp = new Date().toISOString();
		projects = projects
			.map((item) => (item.id === selectedProject.id ? { ...item, updated_at: stamp } : item))
			.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
		selectedProject = { ...selectedProject, updated_at: stamp };
	}

	function uid(prefix) {
		const rnd =
			globalThis.crypto?.randomUUID?.() ??
			`${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
		return `${prefix}-${rnd}`;
	}

	function definition(id) {
		return components.find((component) => component.id === id);
	}

	function snap(value) {
		return Math.round(value / GRID) * GRID;
	}

	function clampPosition(x, y, def) {
		const w = def?.width ?? 120;
		const h = def?.height ?? 100;
		return {
			x: Math.max(0, Math.min(snap(x), CANVAS_W - w)),
			y: Math.max(0, Math.min(snap(y), CANVAS_H - h))
		};
	}

	function addComponent(component, x = 480, y = 280) {
		const { x: px, y: py } = clampPosition(x, y, component);
		const instance = {
			id: uid('part'),
			definition_id: component.id,
			display_name: component.name,
			x: px,
			y: py,
			rotation: 0,
			config: {}
		};
		workbench.placed_components = [...workbench.placed_components, instance];
		selectedComponentId = instance.id;
		selectedWireId = null;
		workbenchDirty = true;
		setStatus('Unsaved changes', true);
	}

	function dragComponent(event, component) {
		event.dataTransfer.setData('text/plain', component.id);
		event.dataTransfer.effectAllowed = 'copy';
	}

	function dropComponent(event) {
		event.preventDefault();
		const component = definition(event.dataTransfer.getData('text/plain'));
		if (!component) return;
		const rect = event.currentTarget.getBoundingClientRect();
		addComponent(
			component,
			event.clientX - rect.left - component.width / 2,
			event.clientY - rect.top - component.height / 2
		);
	}

	function startMove(event, instance) {
		if (event.target.closest('.pin')) return;
		event.preventDefault();
		selectedComponentId = instance.id;
		selectedWireId = null;
		const canvas = event.currentTarget.closest('.workbench');
		const rect = canvas.getBoundingClientRect();
		moving = {
			id: instance.id,
			rect,
			offsetX: event.clientX - rect.left - instance.x,
			offsetY: event.clientY - rect.top - instance.y
		};
		window.addEventListener('pointermove', moveComponent);
		window.addEventListener('pointerup', stopMove, { once: true });
	}

	function moveComponent(event) {
		if (!moving) return;
		const def = definition(
			workbench.placed_components.find((p) => p.id === moving.id)?.definition_id
		);
		const { x, y } = clampPosition(
			event.clientX - moving.rect.left - moving.offsetX,
			event.clientY - moving.rect.top - moving.offsetY,
			def
		);
		workbench.placed_components = workbench.placed_components.map((instance) =>
			instance.id === moving.id ? { ...instance, x, y } : instance
		);
	}

	function stopMove() {
		if (moving) {
			workbenchDirty = true;
			setStatus('Unsaved changes', true);
		}
		moving = null;
		window.removeEventListener('pointermove', moveComponent);
	}

	function pinPosition(instance, pin) {
		return { x: instance.x + pin.x, y: instance.y + pin.y };
	}

	function pinLabel(instanceId, pinName) {
		const instance = workbench.placed_components.find((item) => item.id === instanceId);
		const def = instance ? definition(instance.definition_id) : null;
		const pin = def?.pins.find((item) => item.name === pinName);
		return `${instance?.display_name ?? 'Component'} ${pin?.label ?? pinName}`;
	}

	function pinExists(endpoint) {
		const instance = workbench.placed_components.find((i) => i.id === endpoint.componentId);
		const def = instance ? definition(instance.definition_id) : null;
		return Boolean(def?.pins.some((p) => p.name === endpoint.pinName));
	}

	function clickPin(event, instance, pin) {
		event.stopPropagation();
		selectedComponentId = instance.id;
		selectedWireId = null;

		if (!pendingPin) {
			pendingPin = { componentId: instance.id, pinName: pin.name };
			return;
		}

		if (pendingPin.componentId === instance.id && pendingPin.pinName === pin.name) {
			pendingPin = null;
			return;
		}

		// Prevent duplicate wires between the same two pins.
		const exists = workbench.wires.some((wire) => {
			const a = `${wire.from.componentId}:${wire.from.pinName}`;
			const b = `${wire.to.componentId}:${wire.to.pinName}`;
			const p = `${pendingPin.componentId}:${pendingPin.pinName}`;
			const q = `${instance.id}:${pin.name}`;
			return (a === p && b === q) || (a === q && b === p);
		});
		if (exists) {
			toast('Those pins are already connected.', 'warn');
			pendingPin = null;
			return;
		}

		const wire = {
			id: uid('wire'),
			from: pendingPin,
			to: { componentId: instance.id, pinName: pin.name },
			color: wireColors[workbench.wires.length % wireColors.length],
			label: `${pinLabel(pendingPin.componentId, pendingPin.pinName)} → ${pinLabel(instance.id, pin.name)}`
		};
		workbench.wires = [...workbench.wires, wire];
		pendingPin = null;
		selectedWireId = wire.id;
		workbenchDirty = true;
		setStatus('Unsaved changes', true);
	}

	function wireEndpoint(endpoint) {
		const instance = workbench.placed_components.find((item) => item.id === endpoint.componentId);
		const def = instance ? definition(instance.definition_id) : null;
		const pin = def?.pins.find((item) => item.name === endpoint.pinName);
		return instance && pin ? pinPosition(instance, pin) : { x: 0, y: 0 };
	}

	function wirePath(wire) {
		const from = wireEndpoint(wire.from);
		const to = wireEndpoint(wire.to);
		const dx = Math.abs(to.x - from.x);
		const bow = Math.max(40, dx * 0.5);
		return `M ${from.x} ${from.y} C ${from.x + bow} ${from.y}, ${to.x - bow} ${to.y}, ${to.x} ${to.y}`;
	}

	function deleteSelected() {
		if (selectedWireId) {
			workbench.wires = workbench.wires.filter((wire) => wire.id !== selectedWireId);
			selectedWireId = null;
			workbenchDirty = true;
			setStatus('Unsaved changes', true);
			return;
		}
		if (selectedComponentId) {
			const removed = workbench.placed_components.find((i) => i.id === selectedComponentId);
			workbench.placed_components = workbench.placed_components.filter(
				(item) => item.id !== selectedComponentId
			);
			workbench.wires = workbench.wires.filter(
				(wire) =>
					wire.from.componentId !== selectedComponentId &&
					wire.to.componentId !== selectedComponentId
			);
			selectedComponentId = null;
			workbenchDirty = true;
			setStatus('Unsaved changes', true);
			if (removed) toast(`Removed ${removed.display_name}.`, 'info');
		}
	}

	function rotateSelected() {
		if (!selectedComponentId) return;
		workbench.placed_components = workbench.placed_components.map((item) =>
			item.id === selectedComponentId
				? { ...item, rotation: ((item.rotation ?? 0) + 90) % 360 }
				: item
		);
		workbenchDirty = true;
		setStatus('Unsaved changes', true);
	}

	function clearWorkbench() {
		if (!workbench.placed_components.length) return;
		if (!confirm('Remove every component and wire from the workbench?')) return;
		workbench.placed_components = [];
		workbench.wires = [];
		selectedComponentId = null;
		selectedWireId = null;
		pendingPin = null;
		workbenchDirty = true;
		setStatus('Unsaved changes', true);
	}

	function componentClass(component) {
		return `part ${component.visual_type}`;
	}

	// --- workbench actions used by the context menu -----------------------

	function duplicateComponent(instance) {
		const def = definition(instance.definition_id);
		const { x, y } = clampPosition(instance.x + 28, instance.y + 28, def);
		const copy = {
			...structuredClone(instance),
			id: uid('part'),
			x,
			y
		};
		workbench.placed_components = [...workbench.placed_components, copy];
		selectedComponentId = copy.id;
		selectedWireId = null;
		workbenchDirty = true;
		setStatus('Unsaved changes', true);
		toast(`Duplicated ${instance.display_name}.`, 'info');
	}

	function copyComponent(instance) {
		clipboard = structuredClone(instance);
		toast(`Copied ${instance.display_name}.`, 'info');
	}

	function pasteComponent(x = lastCanvasPoint.x, y = lastCanvasPoint.y) {
		if (!clipboard) return;
		const def = definition(clipboard.definition_id);
		const pos = clampPosition(x, y, def);
		const copy = { ...structuredClone(clipboard), id: uid('part'), x: pos.x, y: pos.y };
		workbench.placed_components = [...workbench.placed_components, copy];
		selectedComponentId = copy.id;
		selectedWireId = null;
		workbenchDirty = true;
		setStatus('Unsaved changes', true);
		toast(`Pasted ${copy.display_name}.`, 'info');
	}

	function bringToFront(instance) {
		workbench.placed_components = [
			...workbench.placed_components.filter((i) => i.id !== instance.id),
			instance
		];
		workbenchDirty = true;
		setStatus('Unsaved changes', true);
	}

	function deleteComponentById(id) {
		const removed = workbench.placed_components.find((i) => i.id === id);
		workbench.placed_components = workbench.placed_components.filter((i) => i.id !== id);
		workbench.wires = workbench.wires.filter(
			(w) => w.from.componentId !== id && w.to.componentId !== id
		);
		if (selectedComponentId === id) selectedComponentId = null;
		workbenchDirty = true;
		setStatus('Unsaved changes', true);
		if (removed) toast(`Removed ${removed.display_name}.`, 'info');
	}

	function rotateComponentById(id) {
		workbench.placed_components = workbench.placed_components.map((item) =>
			item.id === id ? { ...item, rotation: ((item.rotation ?? 0) + 90) % 360 } : item
		);
		workbenchDirty = true;
		setStatus('Unsaved changes', true);
	}

	function setWireColor(wire, color) {
		workbench.wires = workbench.wires.map((w) => (w.id === wire.id ? { ...w, color } : w));
		workbenchDirty = true;
		setStatus('Unsaved changes', true);
	}

	function renameWire(wire) {
		const next = prompt('Wire label', wire.label ?? '');
		if (next === null) return;
		workbench.wires = workbench.wires.map((w) =>
			w.id === wire.id ? { ...w, label: next.trim() || w.label } : w
		);
		workbenchDirty = true;
		setStatus('Unsaved changes', true);
	}

	function deleteWireById(id) {
		workbench.wires = workbench.wires.filter((w) => w.id !== id);
		if (selectedWireId === id) selectedWireId = null;
		workbenchDirty = true;
		setStatus('Unsaved changes', true);
	}

	// --- context menu builders --------------------------------------------

	function recordCanvasPoint(event) {
		const canvas = event.currentTarget.closest('.workbench');
		if (!canvas) return;
		const rect = canvas.getBoundingClientRect();
		lastCanvasPoint = {
			x: event.clientX - rect.left + canvas.scrollLeft,
			y: event.clientY - rect.top + canvas.scrollTop
		};
	}

	function openComponentMenu(event, instance) {
		event.stopPropagation();
		selectedComponentId = instance.id;
		selectedWireId = null;
		contextMenu?.open(event, [
			{ label: instance.display_name, disabled: true, icon: '▣' },
			{ separator: true },
			{ label: 'Rotate 90°', icon: '⟳', shortcut: 'R', onSelect: () => rotateComponentById(instance.id) },
			{ label: 'Duplicate', icon: '⧉', shortcut: 'Ctrl+D', onSelect: () => duplicateComponent(instance) },
			{ label: 'Copy', icon: '⧉', shortcut: 'Ctrl+C', onSelect: () => copyComponent(instance) },
			{ label: 'Bring to front', icon: '⬆', onSelect: () => bringToFront(instance) },
			{ separator: true },
			{ label: 'Delete', icon: '🗑', danger: true, shortcut: 'Del', onSelect: () => deleteComponentById(instance.id) }
		]);
	}

	function openWireMenu(event, wire) {
		event.stopPropagation();
		selectedWireId = wire.id;
		selectedComponentId = null;
		contextMenu?.open(event, [
			{ label: 'Wire', disabled: true, icon: '〜' },
			{ separator: true },
			{
				label: 'Change colour',
				icon: '🎨',
				items: wireColors.map((color, i) => ({
					label: `Colour ${i + 1}`,
					icon: '●',
					onSelect: () => setWireColor(wire, color)
				}))
			},
			{ label: 'Rename label', icon: '✎', onSelect: () => renameWire(wire) },
			{ separator: true },
			{ label: 'Delete wire', icon: '🗑', danger: true, shortcut: 'Del', onSelect: () => deleteWireById(wire.id) }
		]);
	}

	function openCanvasMenu(event) {
		recordCanvasPoint(event);
		const { x, y } = lastCanvasPoint;
		contextMenu?.open(event, [
			{ label: 'Workbench', disabled: true, icon: '▦' },
			{ separator: true },
			{
				label: 'Add component',
				icon: '＋',
				items: components.map((component) => ({
					label: component.name,
					icon: '▸',
					onSelect: () => addComponent(component, x - component.width / 2, y - component.height / 2)
				}))
			},
			{ label: 'Paste', icon: '⧉', shortcut: 'Ctrl+V', disabled: !clipboard, onSelect: () => pasteComponent(x, y) },
			{ separator: true },
			{ label: 'Reset view', icon: '⊙', onSelect: resetView },
			{ label: 'Save workbench', icon: '💾', shortcut: 'Ctrl+S', disabled: !workbenchDirty, onSelect: saveWorkbench },
			{ separator: true },
			{ label: 'Clear workbench', icon: '🗑', danger: true, disabled: !workbench.placed_components.length, onSelect: clearWorkbench }
		]);
	}

	function openProjectMenu(event, project) {
		event.preventDefault();
		event.stopPropagation();
		contextMenu?.open(event, [
			{ label: project.name, disabled: true, icon: '📁' },
			{ separator: true },
			{ label: 'Open', icon: '↗', onSelect: () => openProject(project) },
			{ label: 'Rename', icon: '✎', onSelect: () => startRename(project) },
			{ label: 'Duplicate', icon: '⧉', onSelect: () => duplicateProject(project) },
			{ separator: true },
			{ label: 'Delete', icon: '🗑', danger: true, onSelect: () => deleteProject(project) }
		]);
	}

	function resetView() {
		const canvas = document.querySelector('.workbench');
		if (canvas) canvas.scrollTo({ left: 0, top: 0, behavior: 'smooth' });
	}

	async function duplicateProject(project) {
		busy = true;
		try {
			const created = await api('/api/projects', {
				method: 'POST',
				body: JSON.stringify({
					name: `${project.name} (copy)`,
					description: project.description ?? ''
				})
			});
			// Carry over the workbench layout from the source project.
			const sourceWorkbench = await api(`/api/projects/${project.id}/workbench`);
			await api(`/api/projects/${created.id}/workbench`, {
				method: 'PUT',
				body: JSON.stringify(sourceWorkbench)
			});
			projects = [created, ...projects];
			toast(`Duplicated "${project.name}".`, 'success');
		} catch (error) {
			toast(`Could not duplicate project: ${error.message}`, 'error');
		} finally {
			busy = false;
		}
	}

	function formatDate(value) {
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return 'unknown';
		return date.toLocaleString(undefined, {
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	// --- schematic mini-map: lay components on a grid, route real wires ----
	let schematicNodes = $derived(
		workbench.placed_components.map((instance, index) => ({
			id: instance.id,
			name: instance.display_name,
			x: 20 + (index % 2) * 150,
			y: 22 + Math.floor(index / 2) * 60,
			w: 120,
			h: 38
		}))
	);

	function schematicPath(wire) {
		const from = schematicNodes.find((n) => n.id === wire.from.componentId);
		const to = schematicNodes.find((n) => n.id === wire.to.componentId);
		if (!from || !to) return '';
		const fx = from.x + from.w / 2;
		const fy = from.y + from.h / 2;
		const tx = to.x + to.w / 2;
		const ty = to.y + to.h / 2;
		const mid = (fy + ty) / 2;
		return `M ${fx} ${fy} C ${fx} ${mid}, ${tx} ${mid}, ${tx} ${ty}`;
	}

	let schematicHeight = $derived(
		Math.max(180, 22 + Math.ceil(schematicNodes.length / 2) * 60)
	);
</script>

<svelte:head>
	<title>HardcoreAI Hardware IDE</title>
</svelte:head>

<main class="shell">
	<header class="topbar">
		<div class="brand">
			<span class="logo" aria-hidden="true"></span>
			<div>
				<p class="eyebrow">HardcoreAI</p>
				<h1>Hardware Project IDE</h1>
			</div>
		</div>
		<nav>
			<button class:active={activeView === 'dashboard'} onclick={() => (activeView = 'dashboard')}>
				Projects
			</button>
			<button
				class:active={activeView === 'workbench'}
				disabled={!selectedProject}
				onclick={() => (activeView = 'workbench')}
			>
				Workbench
			</button>
			<button
				class:active={activeView === 'code'}
				disabled={!selectedProject}
				onclick={() => (activeView = 'code')}
			>
				Code
			</button>
		</nav>
		<div class="project-chip">
			<span class="chip-name">{selectedProject?.name ?? 'No project open'}</span>
			<strong class:dirty={workbenchDirty || fileDirty}>
				{#if workbenchDirty || fileDirty}● {saveStatus}{:else}{saveStatus}{/if}
			</strong>
		</div>
	</header>

	<div class="toasts">
		{#each toasts as t (t.id)}
			<div class="toast {t.kind}" transition:fly={{ x: 40, duration: 220 }}>
				<span>{t.message}</span>
				<button onclick={() => (toasts = toasts.filter((x) => x.id !== t.id))} aria-label="Dismiss">
					×
				</button>
			</div>
		{/each}
	</div>

	{#if loading}
		<section class="empty-state big">
			<div class="spinner"></div>
			<p>Loading HardcoreAI…</p>
		</section>
	{:else if activeView === 'dashboard'}
		<section class="dashboard" in:fade={{ duration: 150 }}>
			<form
				class="project-form"
				onsubmit={(event) => {
					event.preventDefault();
					createProject();
				}}
			>
				<div>
					<p class="eyebrow">New project</p>
					<h2>Create a hardware workspace</h2>
				</div>
				<label>
					Project name
					<input bind:value={projectName} maxlength="80" placeholder="e.g. Line Follower" />
				</label>
				<label>
					Description
					<textarea rows="3" bind:value={projectDescription} placeholder="Optional notes"></textarea>
				</label>
				<button class="primary" type="submit" disabled={busy || !projectName.trim()}>
					{busy ? 'Creating…' : 'Create project'}
				</button>
			</form>

			<section class="project-list">
				<div class="section-title">
					<h2>Projects</h2>
					<span>{projects.length} on Supabase</span>
				</div>
				{#if projects.length === 0}
					<div class="empty-state">
						<p>No projects yet.</p>
						<small>Create your first STM32 workspace to open the workbench.</small>
					</div>
				{:else}
					<div class="cards">
						{#each projects as project (project.id)}
							<article
								class="project-card"
								class:current={selectedProject?.id === project.id}
								oncontextmenu={(event) => openProjectMenu(event, project)}
							>
								<div class="card-main">
									{#if renamingProjectId === project.id}
										<!-- svelte-ignore a11y_autofocus -->
										<input
											class="rename-input"
											bind:value={renameDraft}
											autofocus
											onblur={() => commitRename(project)}
											onkeydown={(e) => {
												if (e.key === 'Enter') commitRename(project);
												if (e.key === 'Escape') (renamingProjectId = null);
											}}
										/>
									{:else}
										<h3>{project.name}</h3>
									{/if}
									<p>{project.description || 'No description yet'}</p>
									<span class="meta">Updated {formatDate(project.updated_at)}</span>
								</div>
								<div class="row-actions">
									<button class="primary" onclick={() => openProject(project)}>Open</button>
									<button onclick={() => startRename(project)}>Rename</button>
									<button class="ghost-danger" onclick={() => deleteProject(project)}>
										Delete
									</button>
								</div>
							</article>
						{/each}
					</div>
				{/if}
			</section>
		</section>
	{:else if activeView === 'workbench'}
		<section class="ide-grid" in:fade={{ duration: 150 }}>
			<aside class="palette">
				<div class="section-title">
					<h2>Components</h2>
					<span>{filteredComponents.length}</span>
				</div>
				<input
					class="search"
					placeholder="Search STM32, motor, power…"
					bind:value={componentSearch}
				/>
				<div class="component-list">
					{#each filteredComponents as component (component.id)}
						<button
							class="component-card"
							draggable="true"
							ondragstart={(event) => dragComponent(event, component)}
							onclick={() => addComponent(component)}
							title={`Click to place, or drag onto the workbench`}
						>
							<span class={`thumb ${component.thumbnail}`}></span>
							<span class="component-text">
								<strong>{component.name}</strong>
								<small>{component.category}</small>
								<em>{component.description}</em>
							</span>
						</button>
					{:else}
						<p class="muted">No components match "{componentSearch}".</p>
					{/each}
				</div>
			</aside>

			<section class="workbench-panel">
				<div class="toolbar">
					<div class="toolbar-info">
						<strong>{selectedProject.name}</strong>
						<span class:wiring={pendingPin}>
							{#if pendingPin}
								Wiring from {pinLabel(pendingPin.componentId, pendingPin.pinName)} — click a
								second pin
							{:else}
								Click two pins to create a wire · Del removes selection
							{/if}
						</span>
					</div>
					<div class="row-actions">
						<button onclick={rotateSelected} disabled={!selectedComponentId}>Rotate</button>
						<button
							onclick={deleteSelected}
							disabled={!selectedComponentId && !selectedWireId}
						>
							Delete
						</button>
						<button onclick={clearWorkbench} disabled={!workbench.placed_components.length}>
							Clear
						</button>
						<button onclick={generateFirmware} disabled={busy}>
							{busy ? 'Working…' : 'Generate firmware'}
						</button>
						<button class="primary" onclick={saveWorkbench} disabled={!workbenchDirty}>
							{workbenchDirty ? 'Save workbench' : 'Saved'}
						</button>
					</div>
				</div>

				<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions, a11y_click_events_have_key_events -->
				<div
					class="workbench"
					role="application"
					aria-label="Component workbench"
					tabindex="0"
					ondrop={dropComponent}
					ondragover={(event) => event.preventDefault()}
					oncontextmenu={openCanvasMenu}
					onclick={() => {
						selectedComponentId = null;
						selectedWireId = null;
					}}
				>
					{#if workbench.placed_components.length === 0}
						<div class="canvas-hint">
							<p>Drag a component here</p>
							<small>or click any component in the palette to place it.</small>
						</div>
					{/if}

					<svg
						class="wire-layer"
						viewBox={`0 0 ${CANVAS_W} ${CANVAS_H}`}
						preserveAspectRatio="none"
						aria-label="Workbench wiring"
					>
						{#each workbench.wires as wire (wire.id)}
							{#if pinExists(wire.from) && pinExists(wire.to)}
								<path
									role="button"
									tabindex="0"
									aria-label={wire.label}
									class:selected={wire.id === selectedWireId}
									d={wirePath(wire)}
									stroke={wire.color}
									onclick={(event) => {
										event.stopPropagation();
										selectedWireId = wire.id;
										selectedComponentId = null;
									}}
									oncontextmenu={(event) => openWireMenu(event, wire)}
									onkeydown={(event) => {
										if (event.key === 'Enter' || event.key === ' ') selectedWireId = wire.id;
									}}
								/>
							{/if}
						{/each}
					</svg>

					{#each workbench.placed_components as instance (instance.id)}
						{@const def = definition(instance.definition_id)}
						{#if def}
							<div
								role="button"
								tabindex="0"
								aria-label={instance.display_name}
								class:selected={instance.id === selectedComponentId}
								class={componentClass(def)}
								style={`left:${instance.x}px; top:${instance.y}px; width:${def.width}px; height:${def.height}px; --rot:${instance.rotation ?? 0}deg;`}
								onpointerdown={(event) => startMove(event, instance)}
								oncontextmenu={(event) => openComponentMenu(event, instance)}
								onkeydown={(event) => {
									if (event.key === 'Enter') selectedComponentId = instance.id;
								}}
							>
								<div class="part-body">
									<div class="part-title">
										<strong>{instance.display_name}</strong>
										<small>{def.category}</small>
									</div>

									{#if def.visual_type === 'blue-pill'}
										<div class="usb">USB</div>
										<div class="chip">STM32F103</div>
										<div class="crystal"></div>
										<div class="reset">RST</div>
										<div class="direction">Pin 1</div>
									{:else if def.visual_type === 'motor'}
										<div class="motor-body"><span>M</span></div>
										<div class="shaft"></div>
									{:else if def.visual_type === 'driver'}
										<div class="driver-chip">L298N</div>
										<div class="sink"></div>
									{:else if def.visual_type === 'led'}
										<div class="led-glow"></div>
									{:else if def.visual_type === 'resistor'}
										<div class="resistor-body"></div>
									{:else if def.visual_type === 'battery'}
										<div class="battery-cap"></div>
										<div class="battery-label">9V</div>
									{/if}
								</div>

								{#each def.pins as pin (pin.name)}
									<button
										class:armed={pendingPin?.componentId === instance.id &&
											pendingPin?.pinName === pin.name}
										class={`pin ${pin.side} role-${pin.role}`}
										style={`left:${pin.x}px; top:${pin.y}px;`}
										title={`${pin.label} · ${pin.role}`}
										aria-label={`Pin ${pin.label}, ${pin.role}`}
										onclick={(event) => clickPin(event, instance, pin)}
									>
										<span>{pin.label}</span>
									</button>
								{/each}
							</div>
						{/if}
					{/each}
				</div>
			</section>

			<aside class="schema">
				<div class="section-title">
					<h2>Schematic</h2>
					<span>{workbench.wires.length} wires</span>
				</div>
				<div class="schematic">
					{#if schematicNodes.length === 0}
						<p class="muted small">Place components to see the netlist.</p>
					{:else}
						<svg viewBox={`0 0 320 ${schematicHeight}`} aria-label="Netlist diagram">
							{#each workbench.wires as wire (wire.id)}
								<path class="schem-wire" d={schematicPath(wire)} stroke={wire.color} />
							{/each}
							{#each schematicNodes as node (node.id)}
								<g
									class="schem-node"
									class:selected={node.id === selectedComponentId}
									onclick={() => (selectedComponentId = node.id)}
									role="presentation"
								>
									<rect x={node.x} y={node.y} width={node.w} height={node.h} rx="6" />
									<text x={node.x + node.w / 2} y={node.y + node.h / 2 + 4}>
										{node.name}
									</text>
								</g>
							{/each}
						</svg>
					{/if}
				</div>

				<div class="netlist">
					<h3>Netlist</h3>
					<table>
						<thead>
							<tr><th>From</th><th>To</th></tr>
						</thead>
						<tbody>
							{#each workbench.wires as wire (wire.id)}
								<tr
									class:selected={wire.id === selectedWireId}
									onclick={() => (selectedWireId = wire.id)}
								>
									<td>{pinLabel(wire.from.componentId, wire.from.pinName)}</td>
									<td>{pinLabel(wire.to.componentId, wire.to.pinName)}</td>
								</tr>
							{:else}
								<tr><td colspan="2" class="muted">Wire two pins to build the netlist.</td></tr>
							{/each}
						</tbody>
					</table>
				</div>

				<div class="inspector">
					<h3>Inspector</h3>
					{#if selectedComponent}
						{@const def = definition(selectedComponent.definition_id)}
						<p><strong>{selectedComponent.display_name}</strong></p>
						<p class="muted">{def?.description}</p>
						<dl>
							<div><dt>Category</dt><dd>{def?.category}</dd></div>
							<div><dt>Pins</dt><dd>{def?.pins.length}</dd></div>
							<div>
								<dt>Position</dt>
								<dd>{selectedComponent.x}, {selectedComponent.y}</dd>
							</div>
							<div><dt>Rotation</dt><dd>{selectedComponent.rotation ?? 0}°</dd></div>
						</dl>
					{:else if selectedWire}
						<p><strong>Wire</strong></p>
						<p class="muted">{selectedWire.label}</p>
					{:else}
						<p class="muted">Select a component or wire to inspect it.</p>
					{/if}
				</div>
			</aside>
		</section>
	{:else if activeView === 'code'}
		<section class="code-shell" in:fade={{ duration: 150 }}>
			<aside class="file-tree">
				<div class="section-title">
					<h2>Files</h2>
					<span>{files.length}</span>
				</div>
				{#each files as file (file.path)}
					<button
						class="file-btn"
						class:active={file.path === activeFilePath}
						onclick={() => (activeFilePath = file.path)}
					>
						<span>{file.path}</span>
						<small>{file.language}</small>
					</button>
				{/each}
				<div class="component-summary">
					<h3>Hardware</h3>
					{#each workbench.placed_components as instance (instance.id)}
						<p>{instance.display_name}</p>
					{:else}
						<p class="muted">No hardware placed yet.</p>
					{/each}
				</div>
			</aside>

			<section class="editor-pane">
				<div class="toolbar">
					<div class="toolbar-info">
						<strong>{activeFilePath || 'No file selected'}</strong>
						<span>{fileDirty ? 'Unsaved edits' : 'Component-aware firmware workspace'}</span>
					</div>
					<div class="row-actions">
						<button onclick={generateFirmware} disabled={busy || !selectedProject}>
							Regenerate
						</button>
						<button class="primary" onclick={saveActiveFile} disabled={!activeFile || !fileDirty}>
							{fileDirty ? 'Save file' : 'Saved'}
						</button>
					</div>
				</div>
				{#if activeFile}
					{#key activeFilePath}
						<CodeEditor
							bind:value={activeFile.content}
							language={activeFile.language}
							onchange={() => (fileDirty = true)}
						/>
					{/key}
				{:else}
					<div class="empty-state">
						<p>No file open.</p>
						<small>Select a file from the list to start coding.</small>
					</div>
				{/if}
			</section>

			<aside class="settings-panel">
				<div class="section-title">
					<h2>Project</h2>
					<span>Supabase Postgres</span>
				</div>
				<label>
					Target
					<input value="STM32F103C8T6" readonly />
				</label>
				<label>
					Toolchain
					<input value="ARM GCC (HAL)" readonly />
				</label>
				<div class="stat-grid">
					<div><span>{workbench.placed_components.length}</span><small>components</small></div>
					<div><span>{workbench.wires.length}</span><small>wires</small></div>
					<div><span>{files.length}</span><small>files</small></div>
				</div>
				<p class="muted small">
					Generated firmware lives in <code>src/main.c</code>. Regenerate it whenever the
					workbench changes.
				</p>
			</aside>
		</section>
	{/if}
</main>

<ContextMenu bind:this={contextMenu} />

<style>
	:global(*) {
		box-sizing: border-box;
	}

	:global(html, body) {
		height: 100%;
	}

	:global(body) {
		margin: 0;
		/* Lock the app to the viewport: the page itself never scrolls.
		   Scrolling happens only inside designated regions (component list,
		   code editor, workbench canvas). */
		overflow: hidden;
		background: #14171c;
		color: #eef3f8;
		font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI',
			sans-serif;
		-webkit-font-smoothing: antialiased;
	}

	button,
	input,
	textarea {
		font: inherit;
	}

	button {
		border: 1px solid #343c46;
		background: #222832;
		color: #eef3f8;
		border-radius: 7px;
		padding: 0.5rem 0.8rem;
		cursor: pointer;
		transition: background 0.12s ease, border-color 0.12s ease, transform 0.05s ease;
	}

	button:hover:not(:disabled) {
		background: #2d3541;
		border-color: #45505d;
	}

	button:active:not(:disabled) {
		transform: translateY(1px);
	}

	button:focus-visible {
		outline: 2px solid #74d7bb;
		outline-offset: 2px;
	}

	button:disabled {
		cursor: not-allowed;
		opacity: 0.4;
	}

	input,
	textarea {
		width: 100%;
		border: 1px solid #343c46;
		background: #11151b;
		color: #eef3f8;
		border-radius: 7px;
		padding: 0.6rem 0.7rem;
		transition: border-color 0.12s ease;
	}

	input:focus,
	textarea:focus {
		outline: none;
		border-color: #74d7bb;
	}

	textarea {
		resize: vertical;
	}

	label {
		display: grid;
		gap: 0.4rem;
		color: #aeb8c6;
		font-size: 0.82rem;
	}

	h1,
	h2,
	h3,
	p {
		margin: 0;
	}

	code {
		background: #11151b;
		padding: 0.1rem 0.3rem;
		border-radius: 4px;
		font-size: 0.85em;
	}

	.muted {
		color: #8e9aaa;
	}

	.small {
		font-size: 0.78rem;
	}

	.shell {
		/* Fixed-height app frame: header row + one flexible content row that
		   fills the rest of the viewport. Nothing here grows past 100vh. */
		height: 100vh;
		height: 100dvh;
		display: grid;
		grid-template-rows: auto 1fr;
		overflow: hidden;
	}

	/* ---- topbar ---- */
	.topbar {
		display: grid;
		grid-template-columns: minmax(220px, 1fr) auto minmax(220px, 0.8fr);
		align-items: center;
		gap: 1rem;
		padding: 0.85rem 1.25rem;
		border-bottom: 1px solid #2b333d;
		background: #11151b;
		position: sticky;
		top: 0;
		z-index: 20;
	}

	.brand {
		display: flex;
		align-items: center;
		gap: 0.7rem;
	}

	.logo {
		width: 34px;
		height: 34px;
		border-radius: 9px;
		background: linear-gradient(135deg, #74d7bb, #1f7a65);
		box-shadow: 0 0 18px rgb(116 215 187 / 0.35);
		flex-shrink: 0;
	}

	.eyebrow {
		color: #74d7bb;
		font-size: 0.68rem;
		font-weight: 800;
		letter-spacing: 0.1em;
		text-transform: uppercase;
	}

	.topbar h1 {
		font-size: 1.1rem;
		font-weight: 700;
	}

	nav {
		display: flex;
		gap: 0.4rem;
		background: #0d1014;
		padding: 0.25rem;
		border-radius: 9px;
		border: 1px solid #2b333d;
	}

	nav button {
		border-color: transparent;
		background: transparent;
	}

	nav button.active,
	.file-tree button.active {
		border-color: #2f6b5c;
		background: #17342f;
		color: #b6f0e0;
	}

	.project-chip {
		justify-self: end;
		display: grid;
		gap: 0.15rem;
		text-align: right;
		color: #c9d3df;
		max-width: 100%;
	}

	.chip-name {
		font-size: 0.85rem;
		font-weight: 600;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.project-chip strong {
		color: #74d7bb;
		font-size: 0.74rem;
		font-weight: 600;
	}

	.project-chip strong.dirty {
		color: #f5b95c;
	}

	/* ---- toasts ---- */
	.toasts {
		position: fixed;
		top: 4.5rem;
		right: 1.25rem;
		z-index: 100;
		display: grid;
		gap: 0.5rem;
		max-width: 360px;
	}

	.toast {
		display: flex;
		align-items: flex-start;
		gap: 0.75rem;
		padding: 0.7rem 0.85rem;
		border-radius: 9px;
		background: #1c2530;
		border: 1px solid #2f3a47;
		box-shadow: 0 14px 34px rgb(0 0 0 / 0.45);
		font-size: 0.84rem;
	}

	.toast button {
		border: none;
		background: transparent;
		padding: 0;
		font-size: 1.1rem;
		line-height: 1;
		color: #8e9aaa;
	}

	.toast.success {
		border-color: #2f6b5c;
	}
	.toast.error {
		border-color: #7f2f3b;
		background: #2a1b20;
	}
	.toast.warn {
		border-color: #7a5a26;
		background: #2a2418;
	}

	/* ---- shared panels ---- */
	.dashboard,
	.ide-grid,
	.code-shell {
		padding: 1rem 1.25rem;
		/* Each view occupies exactly the content row of .shell and never
		   pushes the page taller. Inner regions handle their own scroll. */
		min-height: 0;
		height: 100%;
		overflow: hidden;
	}

	.project-form,
	.project-list,
	.palette,
	.schema,
	.file-tree,
	.settings-panel,
	.workbench-panel .toolbar,
	.editor-pane .toolbar {
		background: #11151b;
		border: 1px solid #2b333d;
		border-radius: 10px;
	}

	.section-title,
	.toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
	}

	.section-title h2 {
		font-size: 0.92rem;
	}

	.section-title span,
	.toolbar-info span {
		color: #8e9aaa;
		font-size: 0.76rem;
	}

	.toolbar-info span.wiring {
		color: #74d7bb;
	}

	.row-actions {
		display: flex;
		align-items: center;
		gap: 0.45rem;
		flex-wrap: wrap;
	}

	.primary {
		border-color: #4eb79a;
		background: #1f7a65;
		color: #eafff8;
	}

	.primary:hover:not(:disabled) {
		background: #258b73;
	}

	.ghost-danger {
		border-color: #66323c;
		color: #ffb4bf;
	}

	.ghost-danger:hover:not(:disabled) {
		background: #2a1b20;
	}

	/* ---- dashboard ---- */
	.dashboard {
		display: grid;
		grid-template-columns: minmax(300px, 380px) 1fr;
		grid-template-rows: 100%;
		gap: 1rem;
		align-items: stretch;
	}

	.project-form {
		display: grid;
		gap: 1rem;
		padding: 1.1rem;
		align-content: start;
		/* The form column may scroll on its own if a tall description is
		   typed, but never the page. */
		overflow-y: auto;
	}

	.project-list {
		display: grid;
		grid-template-rows: auto 1fr;
		gap: 0.85rem;
		padding: 1.1rem;
		min-height: 0;
	}

	.cards {
		display: grid;
		gap: 0.7rem;
		align-content: start;
		/* Long project lists scroll inside this region. */
		overflow-y: auto;
		padding-right: 0.2rem;
	}

	.project-card {
		display: flex;
		justify-content: space-between;
		gap: 1rem;
		padding: 1rem;
		border: 1px solid #2b333d;
		border-radius: 9px;
		background: #171c23;
		transition: border-color 0.12s ease, transform 0.08s ease;
	}

	.project-card:hover {
		border-color: #3a4654;
	}

	.project-card.current {
		border-color: #2f6b5c;
		background: #15211f;
	}

	.card-main {
		display: grid;
		gap: 0.3rem;
		min-width: 0;
	}

	.project-card h3 {
		font-size: 1rem;
	}

	.project-card p {
		color: #aeb8c6;
		font-size: 0.85rem;
	}

	.project-card .meta {
		color: #71808f;
		font-size: 0.74rem;
	}

	.rename-input {
		font-size: 1rem;
		font-weight: 600;
		padding: 0.3rem 0.4rem;
	}

	.empty-state {
		display: grid;
		place-items: center;
		gap: 0.35rem;
		text-align: center;
		padding: 2.5rem 1rem;
		color: #8e9aaa;
	}

	.empty-state.big {
		min-height: 60vh;
	}

	.empty-state p {
		color: #c9d3df;
		font-weight: 600;
	}

	.spinner {
		width: 30px;
		height: 30px;
		border: 3px solid #2b333d;
		border-top-color: #74d7bb;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	/* ---- IDE grid ---- */
	.ide-grid {
		display: grid;
		grid-template-columns: 290px minmax(520px, 1fr) 340px;
		/* One full-height row so the three panels stretch to the viewport
		   bottom instead of collapsing to their content height. */
		grid-template-rows: 100%;
		gap: 1rem;
	}

	.palette,
	.schema {
		display: grid;
		grid-template-rows: auto auto 1fr;
		gap: 0.7rem;
		padding: 1rem;
		/* Fill the grid row exactly; inner lists scroll, the panel does not. */
		min-height: 0;
		height: 100%;
		overflow: hidden;
	}

	.schema {
		/* title · schematic · netlist (flexes + scrolls) · inspector */
		grid-template-rows: auto auto 1fr auto;
	}

	.search {
		background: #0d1014;
	}

	.component-list {
		overflow-y: auto;
		display: grid;
		align-content: start;
		gap: 0.55rem;
		padding-right: 0.2rem;
	}

	.component-card {
		display: grid;
		grid-template-columns: 56px 1fr;
		gap: 0.7rem;
		text-align: left;
		padding: 0.65rem;
		align-items: center;
	}

	.component-text {
		display: grid;
		gap: 0.1rem;
		min-width: 0;
	}

	.component-card strong {
		font-size: 0.88rem;
	}

	.component-card small {
		color: #74d7bb;
		font-size: 0.7rem;
	}

	.component-card em {
		color: #9aa6b5;
		font-size: 0.74rem;
		font-style: normal;
		line-height: 1.35;
	}

	/* Component chip visuals (.thumb*, .part*, .pin*) live in
	   $lib/chip_styles.css — keyed by the DB `visual_type`. */

	/* ---- workbench ---- */
	.workbench-panel {
		display: grid;
		grid-template-rows: auto 1fr;
		gap: 0.7rem;
		min-height: 0;
		height: 100%;
	}

	.toolbar {
		padding: 0.7rem 0.85rem;
	}

	.toolbar-info {
		display: grid;
		gap: 0.15rem;
		min-width: 0;
	}

	.workbench {
		position: relative;
		/* Fills the 1fr row of .workbench-panel. The canvas scrolls
		   internally for the full 1600x1000 design surface. */
		min-height: 0;
		height: 100%;
		overflow: auto;
		border: 1px solid #2b333d;
		border-radius: 10px;
		background:
			linear-gradient(#222a33 1px, transparent 1px),
			linear-gradient(90deg, #222a33 1px, transparent 1px),
			#181d24;
		background-size: 24px 24px;
	}

	.canvas-hint {
		position: absolute;
		inset: 0;
		display: grid;
		place-content: center;
		gap: 0.3rem;
		text-align: center;
		color: #5d6877;
		pointer-events: none;
	}

	.canvas-hint p {
		font-size: 1.05rem;
		font-weight: 600;
	}

	.wire-layer {
		position: absolute;
		top: 0;
		left: 0;
		width: 1600px;
		height: 1000px;
		pointer-events: none;
	}

	.wire-layer path {
		fill: none;
		stroke-width: 4;
		stroke-linecap: round;
		pointer-events: stroke;
		cursor: pointer;
		transition: stroke-width 0.1s ease;
	}

	.wire-layer path:hover {
		stroke-width: 5.5;
	}

	.wire-layer path.selected {
		stroke-width: 7;
		filter: drop-shadow(0 0 7px currentColor);
	}

	/* ---- schematic ---- */
	.schematic {
		border: 1px solid #2b333d;
		background: #171c23;
		border-radius: 9px;
		padding: 0.5rem;
		min-height: 120px;
		display: grid;
		place-items: center;
	}

	.schematic svg {
		width: 100%;
		height: auto;
	}

	.schem-node rect {
		fill: #222832;
		stroke: #526071;
		transition: fill 0.1s ease, stroke 0.1s ease;
		cursor: pointer;
	}

	.schem-node:hover rect {
		stroke: #74d7bb;
	}

	.schem-node.selected rect {
		fill: #17342f;
		stroke: #74d7bb;
	}

	.schem-node text {
		fill: #eef3f8;
		font-size: 10px;
		text-anchor: middle;
		pointer-events: none;
	}

	.schem-wire {
		fill: none;
		stroke-width: 2;
	}

	.netlist {
		display: grid;
		grid-template-rows: auto 1fr;
		gap: 0.4rem;
		min-height: 0;
		overflow-y: auto;
		align-content: start;
	}

	.netlist h3,
	.inspector h3 {
		color: #eef3f8;
		font-size: 0.85rem;
	}

	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.75rem;
	}

	th,
	td {
		border-bottom: 1px solid #2b333d;
		padding: 0.5rem 0.35rem;
		text-align: left;
		vertical-align: top;
	}

	th {
		color: #8e9aaa;
		font-weight: 600;
	}

	tbody tr {
		cursor: pointer;
	}

	tbody tr:hover td {
		background: #161d24;
	}

	tr.selected td {
		background: #17342f;
	}

	.inspector {
		align-self: end;
		display: grid;
		gap: 0.4rem;
		color: #aeb8c6;
		font-size: 0.83rem;
		border-top: 1px solid #2b333d;
		padding-top: 0.7rem;
	}

	.inspector dl {
		margin: 0.2rem 0 0;
		display: grid;
		gap: 0.3rem;
	}

	.inspector dl div {
		display: flex;
		justify-content: space-between;
		gap: 1rem;
	}

	.inspector dt {
		color: #71808f;
	}

	.inspector dd {
		margin: 0;
		color: #d4dce5;
	}

	/* ---- code view ---- */
	.code-shell {
		display: grid;
		grid-template-columns: 250px minmax(500px, 1fr) 290px;
		grid-template-rows: 100%;
		gap: 1rem;
	}

	.file-tree,
	.settings-panel {
		display: grid;
		align-content: start;
		gap: 0.65rem;
		padding: 1rem;
		/* Fill the row; scroll internally if the file list is long. */
		min-height: 0;
		height: 100%;
		overflow-y: auto;
	}

	.file-btn {
		display: flex;
		justify-content: space-between;
		gap: 0.75rem;
		text-align: left;
		align-items: center;
	}

	.file-btn small {
		color: #74d7bb;
		text-transform: uppercase;
		font-size: 0.62rem;
	}

	.component-summary {
		margin-top: 0.4rem;
		display: grid;
		gap: 0.35rem;
		color: #aeb8c6;
		font-size: 0.82rem;
		border-top: 1px solid #2b333d;
		padding-top: 0.6rem;
	}

	.component-summary h3 {
		font-size: 0.85rem;
		color: #eef3f8;
	}

	.editor-pane {
		min-height: 0;
		display: grid;
		grid-template-rows: auto 1fr;
		gap: 0.7rem;
		height: 100%;
	}

	.editor-pane > :global(.editor) {
		border: 1px solid #2b333d;
		border-radius: 10px;
		overflow: hidden;
		/* Editor fills the 1fr row; its textarea scrolls inside. */
		min-height: 0;
		height: 100%;
	}

	.stat-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 0.5rem;
	}

	.stat-grid div {
		background: #171c23;
		border: 1px solid #2b333d;
		border-radius: 8px;
		padding: 0.6rem 0.4rem;
		text-align: center;
		display: grid;
		gap: 0.15rem;
	}

	.stat-grid span {
		font-size: 1.2rem;
		font-weight: 700;
		color: #74d7bb;
	}

	.stat-grid small {
		color: #8e9aaa;
		font-size: 0.68rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	/* ---- responsive ---- */
	@media (max-width: 1180px) {
		.dashboard,
		.ide-grid,
		.code-shell {
			grid-template-columns: 1fr;
		}

		.topbar {
			grid-template-columns: 1fr auto;
			grid-template-areas: 'brand chip' 'nav nav';
		}

		.brand {
			grid-area: brand;
		}
		nav {
			grid-area: nav;
		}
		.project-chip {
			grid-area: chip;
		}

		.palette,
		.schema,
		.file-tree,
		.settings-panel {
			max-height: none;
		}

		.workbench {
			height: 70vh;
		}

		.editor-pane {
			height: 70vh;
		}
	}
</style>
