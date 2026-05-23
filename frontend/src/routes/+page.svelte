<script>
	import { onMount } from 'svelte';
	import { fade, fly } from 'svelte/transition';
	import CodeEditor from '$lib/CodeEditor.svelte';
	import ContextMenu from '$lib/ContextMenu.svelte';
	import AssistantPanel from '$lib/AssistantPanel.svelte';
	import { background } from '$lib/chip_symbols.js';
	import { compatibility, connectionWarning, canConnect, ROLE_LABEL } from '$lib/wiring.js';
	import { supabase } from '$lib/supabase.js';

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
	let selectedIds = $state([]); // multi-select: every picked component instance
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

	// Emulator States
	let emulatorBusy = $state(false);
	let debuggerConnected = $state(false);
	let debuggerRunning = $state(false);
	let qemuRunning = $state(false);
	let pioStatus = $state('Idle');
	let terminalLog = $state(['HardcoreApp Emulator Terminal Initialized.']);
	let qemuLog = $state([]);
	let registersData = $state('');

	// Auth States
	let session = $state(null);
	let user = $state(null);
	let authEmail = $state('');
	let authPassword = $state('');
	let authMode = $state('login');
	let authLoading = $state(false);

	// Captcha States
	let captchaCode = $state('');
	let captchaInput = $state('');

	function generateCaptcha() {
		const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
		let code = '';
		for (let i = 0; i < 5; i++) {
			code += chars.charAt(Math.floor(Math.random() * chars.length));
		}
		captchaCode = code;
		captchaInput = '';
	}

	function setAuthMode(mode) {
		authMode = mode;
		authEmail = '';
		authPassword = '';
		generateCaptcha();
	}

	// Account Menu States
	let accountMenuOpen = $state(false);
	let newPassword = $state('');
	let passwordLoading = $state(false);

	function toggleAccountMenu(e) {
		e.stopPropagation();
		accountMenuOpen = !accountMenuOpen;
	}

	function closeAccountMenu() {
		accountMenuOpen = false;
	}

	async function handleChangePassword(event) {
		event.preventDefault();
		if (!newPassword || newPassword.length < 6) {
			toast('Password must be at least 6 characters.', 'error');
			return;
		}
		passwordLoading = true;
		try {
			const { error } = await supabase.auth.updateUser({ password: newPassword });
			if (error) throw error;
			toast('Password updated successfully!', 'success');
			newPassword = '';
			accountMenuOpen = false;
		} catch (error) {
			toast(`Failed to update password: ${error.message}`, 'error');
		} finally {
			passwordLoading = false;
		}
	}

	let contextMenu = $state(null);
	let clipboard = $state(null); // a copied placed-component instance
	let lastCanvasPoint = $state({ x: 480, y: 280 });

	// Drag-to-wire: an in-progress wire being dragged from a pin. `cursor` is the
	// live pointer position in canvas space; `hover` is the pin under it (if any).
	let wiring = $state(null); // { from:{componentId,pinName,role}, cursor:{x,y}, hover }
	let schematicCollapsed = $state({}); // instanceId -> bool, schematic panel folds

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

	// The components shown in the Schematic pin panel: whatever is multi-selected,
	// or — when nothing is selected — every placed component.
	let schematicComponents = $derived(
		selectedIds.length
			? workbench.placed_components.filter((c) => selectedIds.includes(c.id))
			: workbench.placed_components
	);

	onMount(async () => {
		const source = new EventSource('http://localhost:8080/qemu/stream');
		source.onmessage = (event) => {
			qemuLog = [...qemuLog, event.data];
		};

		generateCaptcha();
		const { data: { subscription } } = supabase.auth.onAuthStateChange(async (_event, newSession) => {
			session = newSession;
			user = newSession?.user ?? null;
			if (user) {
				loading = true;
				await Promise.all([loadComponents(), loadProjects()]);
				loading = false;
			} else {
				projects = [];
				selectedProject = null;
				clearSelection();
				loading = false;
			}
		});

		window.addEventListener('keydown', handleGlobalKey);
		window.addEventListener('beforeunload', warnUnsaved);
		window.addEventListener('click', closeAccountMenu);
		return () => {
			subscription.unsubscribe();
			window.removeEventListener('keydown', handleGlobalKey);
			window.removeEventListener('beforeunload', warnUnsaved);
			window.removeEventListener('click', closeAccountMenu);
		};
	});

	async function handleEmailAuth(event) {
		event.preventDefault();
		if (!authEmail.trim() || !authPassword) {
			toast('Email and password are required.', 'error');
			return;
		}
		if (captchaInput.toUpperCase() !== captchaCode) {
			toast('Captcha verification failed. Please try again.', 'error');
			generateCaptcha();
			return;
		}
		authLoading = true;
		try {
			if (authMode === 'login') {
				const { error } = await supabase.auth.signInWithPassword({
					email: authEmail.trim(),
					password: authPassword
				});
				if (error) throw error;
				toast('Welcome back!', 'success');
			} else {
				const { error } = await supabase.auth.signUp({
					email: authEmail.trim(),
					password: authPassword
				});
				if (error) throw error;
				toast('Registration successful! Please check your email.', 'success');
			}
		} catch (error) {
			toast(error.message, 'error');
		} finally {
			authLoading = false;
		}
	}

	async function handleGoogleLogin() {
		authLoading = true;
		try {
			const { error } = await supabase.auth.signInWithOAuth({
				provider: 'google',
				options: {
					redirectTo: window.location.origin
				}
			});
			if (error) throw error;
		} catch (error) {
			toast(error.message, 'error');
		} finally {
			authLoading = false;
		}
	}

	async function handleLogout() {
		if (workbenchDirty || fileDirty) {
			if (!confirm('You have unsaved changes. Log out anyway?')) return;
		}
		try {
			await supabase.auth.signOut();
			toast('Logged out.', 'info');
		} catch (error) {
			toast(error.message, 'error');
		}
	}

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
			if ((event.key === 'Delete' || event.key === 'Backspace') && (selectedIds.length || selectedWireId)) {
				event.preventDefault();
				deleteSelected();
			}
			if (event.key === 'Escape') {
				clearSelection();
				pendingPin = null;
				wiring = null;
				contextMenu?.close();
			}
			if (mod && event.key === 'a') {
				event.preventDefault();
				selectAllComponents();
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
		const token = session?.access_token;
		const headers = {
			'Content-Type': 'application/json',
			...(options.headers ?? {})
		};
		if (token) {
			headers['Authorization'] = `Bearer ${token}`;
		}
		const response = await fetch(`${API_BASE}${path}`, {
			...options,
			headers
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

	function logTerminal(msg) {
		const timestamp = new Date().toLocaleTimeString();
		terminalLog = [...terminalLog, `[${timestamp}] ${msg}`];
	}

	async function runBuild() {
		emulatorBusy = true;
		pioStatus = 'Building...';
		logTerminal('Running PlatformIO Build...');
		try {
			const res = await fetch('http://localhost:8080/platformio/build', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ projectPath: './Blinky', files })
			});
			const data = await res.json();
			if (!data.success) throw new Error(data.error || 'Unknown build error');
			logTerminal(data.output);
			pioStatus = 'Build complete';
		} catch(err) {
			logTerminal('Build failed: ' + err.message);
			pioStatus = 'Build failed';
		}
		emulatorBusy = false;
	}

	async function runFlash() {
		emulatorBusy = true;
		pioStatus = 'Flashing...';
		logTerminal('Running PlatformIO Flash...');
		try {
			const res = await fetch('http://localhost:8080/platformio/flash', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ projectPath: './Blinky', files })
			});
			const data = await res.json();
			if (!data.success) throw new Error(data.error || 'Unknown flash error');
			logTerminal(data.output);
			pioStatus = 'Flash complete';
		} catch(err) {
			logTerminal('Flash failed: ' + err.message);
			pioStatus = 'Flash failed';
		}
		emulatorBusy = false;
	}

	async function runEmulator() {
		emulatorBusy = true;
		pioStatus = 'Starting QEMU...';
		logTerminal('Starting QEMU Emulator...');
		try {
			const res = await fetch('http://localhost:8080/qemu/run');
			const text = await res.text();
			logTerminal(text);
			pioStatus = 'QEMU running';
			qemuRunning = true;
		} catch(err) {
			logTerminal('Emulator failed: ' + err.message);
			pioStatus = 'QEMU failed';
		}
		emulatorBusy = false;
	}

	async function runConnect() {
		emulatorBusy = true;
		logTerminal('Connecting GDB Debugger...');
		try {
			const res = await fetch('http://localhost:8080/debug/connect');
			if (!res.ok) throw new Error(await res.text());
			const text = await res.text();
			logTerminal(text);
			debuggerConnected = true;
			debuggerRunning = false; // Initially halted by QEMU -S
			await fetchRegisters();
		} catch(err) {
			logTerminal('Debugger connection failed: ' + err.message);
		}
		emulatorBusy = false;
	}

	async function runHalt() {
		try {
			const res = await fetch('http://localhost:8080/debug/halt');
			if (!res.ok) throw new Error(await res.text());
			logTerminal(await res.text());
			debuggerRunning = false;
			await fetchRegisters();
		} catch(err) {
			logTerminal('Halt failed: ' + err.message);
		}
	}

	async function runContinue() {
		try {
			debuggerRunning = true;
			const res = await fetch('http://localhost:8080/debug/continue');
			if (!res.ok) throw new Error(await res.text());
			logTerminal(await res.text());
		} catch(err) {
			logTerminal('Continue failed: ' + err.message);
			debuggerRunning = false;
		}
	}

	async function runStep() {
		try {
			const res = await fetch('http://localhost:8080/debug/step');
			if (!res.ok) throw new Error(await res.text());
			logTerminal(await res.text());
			debuggerRunning = false;
			await fetchRegisters();
		} catch(err) {
			logTerminal('Step failed: ' + err.message);
		}
	}

	async function fetchRegisters() {
		try {
			const res = await fetch('http://localhost:8080/debug/registers');
			if (!res.ok) throw new Error(await res.text());
			registersData = await res.text();
			logTerminal('Registers read:\n' + registersData);
		} catch(err) {
			logTerminal('Read registers failed: ' + err.message);
		}
	}

	/** Called by the AI panel once the two-phase agent finishes. The agent has
	 *  already written the netlist and code files to the database, so we just
	 *  re-pull both into the editor and surface its summary as a toast. */
	async function onAgentDone(runResult) {
		if (!selectedProject) return;
		try {
			await Promise.all([
				loadWorkbench(selectedProject.id),
				loadFiles(selectedProject.id)
			]);
			workbenchDirty = false;
			fileDirty = false;
			// Show generated main.c if the coding phase produced one.
			if (files.some((f) => f.path === 'src/main.c')) activeFilePath = 'src/main.c';
			touchProjectTimestamp();
			const wired = runResult?.wiring?.steps?.length ?? 0;
			const coded = runResult?.coding?.steps?.length ?? 0;
			toast(`AI agent done — ${wired} wiring step(s), ${coded} coding step(s).`, 'success');
		} catch (error) {
			toast(`Could not reload after the agent ran: ${error.message}`, 'error');
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
		selectComponent(instance.id);
		workbenchDirty = true;
		setStatus('Unsaved changes', true);
	}

	// --- selection ---------------------------------------------------------
	// `selectedComponentId` is kept as the "primary" of the selection so the
	// existing single-target actions (rotate, inspector) keep working.

	/** Select a component. `additive` (Shift/Ctrl-click) toggles it in/out of
	 *  the multi-selection instead of replacing it. */
	function selectComponent(id, additive = false) {
		selectedWireId = null;
		if (additive) {
			selectedIds = selectedIds.includes(id)
				? selectedIds.filter((x) => x !== id)
				: [...selectedIds, id];
		} else {
			selectedIds = [id];
		}
		selectedComponentId = selectedIds[selectedIds.length - 1] ?? null;
	}

	function clearSelection() {
		selectedIds = [];
		selectedComponentId = null;
		selectedWireId = null;
	}

	function isSelected(id) {
		return selectedIds.includes(id);
	}

	/** Select every placed component (Ctrl+A on the workbench). */
	function selectAllComponents() {
		selectedIds = workbench.placed_components.map((c) => c.id);
		selectedComponentId = selectedIds[selectedIds.length - 1] ?? null;
		selectedWireId = null;
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
		if (event.button !== 0) return;
		event.preventDefault();
		const additive = event.shiftKey || event.ctrlKey || event.metaKey;
		// Click on an already-selected member keeps the whole group; otherwise
		// (re)set the selection to this instance.
		if (!isSelected(instance.id) || additive) {
			selectComponent(instance.id, additive);
		} else {
			selectedComponentId = instance.id;
			selectedWireId = null;
		}
		const canvas = event.currentTarget.closest('.workbench');
		const rect = canvas.getBoundingClientRect();
		// Move every selected component together; remember each one's grab offset.
		const group = workbench.placed_components.filter((c) => selectedIds.includes(c.id));
		moving = {
			rect,
			members: group.map((c) => ({
				id: c.id,
				offsetX: event.clientX - rect.left - c.x,
				offsetY: event.clientY - rect.top - c.y
			}))
		};
		window.addEventListener('pointermove', moveComponent);
		window.addEventListener('pointerup', stopMove, { once: true });
	}

	function moveComponent(event) {
		if (!moving) return;
		const next = new Map();
		for (const member of moving.members) {
			const def = definition(
				workbench.placed_components.find((p) => p.id === member.id)?.definition_id
			);
			next.set(
				member.id,
				clampPosition(
					event.clientX - moving.rect.left - member.offsetX,
					event.clientY - moving.rect.top - member.offsetY,
					def
				)
			);
		}
		workbench.placed_components = workbench.placed_components.map((instance) =>
			next.has(instance.id) ? { ...instance, ...next.get(instance.id) } : instance
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

	/** The pin's signal role ('gpio', 'power', ...) for compatibility checks. */
	function pinRole(instanceId, pinName) {
		const instance = workbench.placed_components.find((item) => item.id === instanceId);
		const def = instance ? definition(instance.definition_id) : null;
		return def?.pins.find((item) => item.name === pinName)?.role ?? 'gpio';
	}

	/** True if this exact pin already has at least one wire on it. */
	function pinIsWired(instanceId, pinName) {
		return workbench.wires.some(
			(w) =>
				(w.from.componentId === instanceId && w.from.pinName === pinName) ||
				(w.to.componentId === instanceId && w.to.pinName === pinName)
		);
	}

	/** Does a wire already join these two specific pins (either direction)? */
	function wireExists(a, b) {
		return workbench.wires.some((wire) => {
			const w1 = `${wire.from.componentId}:${wire.from.pinName}`;
			const w2 = `${wire.to.componentId}:${wire.to.pinName}`;
			const p = `${a.componentId}:${a.pinName}`;
			const q = `${b.componentId}:${b.pinName}`;
			return (w1 === p && w2 === q) || (w1 === q && w2 === p);
		});
	}

	/** Create a wire between two endpoints. Returns true if one was added.
	 *  Honours the warn-but-allow policy: any pair connects, dubious ones toast. */
	function createWire(a, b) {
		if (!canConnect(a, b)) return false;
		if (wireExists(a, b)) {
			toast('Those pins are already connected.', 'warn');
			return false;
		}
		const roleA = pinRole(a.componentId, a.pinName);
		const roleB = pinRole(b.componentId, b.pinName);
		const wire = {
			id: uid('wire'),
			from: { componentId: a.componentId, pinName: a.pinName },
			to: { componentId: b.componentId, pinName: b.pinName },
			color: wireColors[workbench.wires.length % wireColors.length],
			label: `${pinLabel(a.componentId, a.pinName)} → ${pinLabel(b.componentId, b.pinName)}`
		};
		workbench.wires = [...workbench.wires, wire];
		selectedWireId = wire.id;
		workbenchDirty = true;
		setStatus('Unsaved changes', true);
		const warning = connectionWarning(roleA, roleB);
		if (warning) toast(warning, 'warn');
		return true;
	}

	function pinExists(endpoint) {
		const instance = workbench.placed_components.find((i) => i.id === endpoint.componentId);
		const def = instance ? definition(instance.definition_id) : null;
		return Boolean(def?.pins.some((p) => p.name === endpoint.pinName));
	}

	// --- wiring: drag a pin onto another, or click two pins in turn ---------

	/** Pointer pressed on a pin. Starts a drag-wire; if a `pendingPin` is armed
	 *  (click-to-wire mode) we leave it — `clickPin` on pointerup completes it. */
	function startWire(event, instance, pin) {
		if (event.button !== 0) return;
		event.stopPropagation();
		event.preventDefault();
		selectComponent(instance.id, event.shiftKey || event.ctrlKey || event.metaKey);
		const canvas = event.currentTarget.closest('.workbench');
		const rect = canvas?.getBoundingClientRect();
		wiring = {
			from: { componentId: instance.id, pinName: pin.name, role: pin.role },
			rect,
			scroll: { x: canvas?.scrollLeft ?? 0, y: canvas?.scrollTop ?? 0 },
			cursor: pinPosition(instance, pin),
			hover: null,
			moved: false
		};
		window.addEventListener('pointermove', dragWire);
		window.addEventListener('pointerup', endWire, { once: true });
	}

	function dragWire(event) {
		if (!wiring || !wiring.rect) return;
		wiring.moved = true;
		wiring.cursor = {
			x: event.clientX - wiring.rect.left + wiring.scroll.x,
			y: event.clientY - wiring.rect.top + wiring.scroll.y
		};
		// Find a pin button under the pointer to snap/highlight.
		const el = document.elementFromPoint(event.clientX, event.clientY)?.closest('.pin');
		if (el && el.dataset.componentId && el.dataset.pinName) {
			wiring.hover = { componentId: el.dataset.componentId, pinName: el.dataset.pinName };
		} else {
			wiring.hover = null;
		}
	}

	function endWire(event) {
		window.removeEventListener('pointermove', dragWire);
		if (!wiring) return;
		const drag = wiring;
		wiring = null;

		// A press without movement = click-to-wire: fall through to clickPin.
		if (!drag.moved) {
			const inst = workbench.placed_components.find((c) => c.id === drag.from.componentId);
			const def = inst ? definition(inst.definition_id) : null;
			const pin = def?.pins.find((p) => p.name === drag.from.pinName);
			if (inst && pin) clickPin(inst, pin);
			return;
		}

		// A real drag: connect to whatever pin we were released over.
		const target =
			drag.hover ??
			(() => {
				const el = document
					.elementFromPoint(event.clientX, event.clientY)
					?.closest('.pin');
				return el?.dataset.componentId
					? { componentId: el.dataset.componentId, pinName: el.dataset.pinName }
					: null;
			})();
		if (target) {
			createWire(
				{ componentId: drag.from.componentId, pinName: drag.from.pinName },
				target
			);
		}
		pendingPin = null;
	}

	/** Click-to-wire fallback: first click arms a pin, second click connects. */
	function clickPin(instance, pin) {
		selectComponent(instance.id);
		const here = { componentId: instance.id, pinName: pin.name };
		if (!pendingPin) {
			pendingPin = here;
			return;
		}
		if (pendingPin.componentId === here.componentId && pendingPin.pinName === here.pinName) {
			pendingPin = null;
			return;
		}
		createWire(pendingPin, here);
		pendingPin = null;
	}

	/** Live highlight state for a pin while a drag-wire is in progress.
	 *  Returns '' | 'compat-ideal' | 'compat-ok' | 'compat-warn' | 'compat-self'. */
	function pinDragState(instanceId, pinName, pinRoleValue) {
		if (!wiring) return '';
		const from = wiring.from;
		if (from.componentId === instanceId && from.pinName === pinName) return 'compat-self';
		if (
			wireExists(
				{ componentId: from.componentId, pinName: from.pinName },
				{ componentId: instanceId, pinName: pinName }
			)
		)
			return 'compat-warn';
		return `compat-${compatibility(from.role, pinRoleValue)}`;
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
		if (selectedIds.length) {
			const removed = workbench.placed_components.filter((i) => selectedIds.includes(i.id));
			const gone = new Set(selectedIds);
			workbench.placed_components = workbench.placed_components.filter(
				(item) => !gone.has(item.id)
			);
			workbench.wires = workbench.wires.filter(
				(wire) => !gone.has(wire.from.componentId) && !gone.has(wire.to.componentId)
			);
			clearSelection();
			workbenchDirty = true;
			setStatus('Unsaved changes', true);
			if (removed.length === 1) toast(`Removed ${removed[0].display_name}.`, 'info');
			else if (removed.length > 1) toast(`Removed ${removed.length} components.`, 'info');
		}
	}

	function rotateSelected() {
		if (!selectedIds.length) return;
		const ids = new Set(selectedIds);
		workbench.placed_components = workbench.placed_components.map((item) =>
			ids.has(item.id)
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
		clearSelection();
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
		selectComponent(copy.id);
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
		selectComponent(copy.id);
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
		selectedIds = selectedIds.filter((x) => x !== id);
		if (selectedComponentId === id) selectedComponentId = selectedIds.at(-1) ?? null;
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
		// Right-clicking outside the current group selects just this one.
		if (!isSelected(instance.id)) selectComponent(instance.id);
		else selectedWireId = null;
		const multi = selectedIds.length > 1 && isSelected(instance.id);
		contextMenu?.open(event, [
			{
				label: multi ? `${selectedIds.length} components` : instance.display_name,
				disabled: true,
				icon: '▣'
			},
			{ separator: true },
			{ label: multi ? 'Rotate selection' : 'Rotate 90°', icon: '⟳', shortcut: 'R', onSelect: rotateSelected },
			{ label: 'Duplicate', icon: '⧉', shortcut: 'Ctrl+D', onSelect: () => duplicateComponent(instance) },
			{ label: 'Copy', icon: '⧉', shortcut: 'Ctrl+C', onSelect: () => copyComponent(instance) },
			{ label: 'Bring to front', icon: '⬆', onSelect: () => bringToFront(instance) },
			{ separator: true },
			{
				label: multi ? `Delete ${selectedIds.length} components` : 'Delete',
				icon: '🗑',
				danger: true,
				shortcut: 'Del',
				onSelect: multi ? deleteSelected : () => deleteComponentById(instance.id)
			}
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

	// --- schematic pin panel ----------------------------------------------
	// The schematic is an interactive pin list. Each placed (or selected)
	// component is a foldable row; every pin is draggable to wire it up.

	function toggleSchematicFold(id) {
		schematicCollapsed = { ...schematicCollapsed, [id]: !schematicCollapsed[id] };
	}

	/** All wires touching a given pin, with the far endpoint resolved to text. */
	function pinConnections(instanceId, pinName) {
		return workbench.wires
			.filter(
				(w) =>
					(w.from.componentId === instanceId && w.from.pinName === pinName) ||
					(w.to.componentId === instanceId && w.to.pinName === pinName)
			)
			.map((w) => {
				const near = w.from.componentId === instanceId && w.from.pinName === pinName;
				const far = near ? w.to : w.from;
				return { wireId: w.id, color: w.color, label: pinLabel(far.componentId, far.pinName) };
			});
	}

	// --- schematic-panel drag-to-wire -------------------------------------
	// Mirrors the workbench wiring, but anchored to the pin rows in the panel.

	function startSchematicWire(event, instance, pin) {
		if (event.button !== 0) return;
		event.stopPropagation();
		event.preventDefault();
		wiring = {
			from: { componentId: instance.id, pinName: pin.name, role: pin.role },
			rect: null,
			scroll: { x: 0, y: 0 },
			cursor: { x: 0, y: 0 },
			hover: null,
			moved: false,
			source: 'schematic'
		};
		window.addEventListener('pointermove', dragSchematicWire);
		window.addEventListener('pointerup', endSchematicWire, { once: true });
	}

	function dragSchematicWire(event) {
		if (!wiring) return;
		wiring.moved = true;
		const row = document
			.elementFromPoint(event.clientX, event.clientY)
			?.closest('.schem-pin');
		if (row && row.dataset.componentId && row.dataset.pinName) {
			wiring.hover = { componentId: row.dataset.componentId, pinName: row.dataset.pinName };
		} else {
			wiring.hover = null;
		}
	}

	function endSchematicWire(event) {
		window.removeEventListener('pointermove', dragSchematicWire);
		if (!wiring) return;
		const drag = wiring;
		wiring = null;
		const target =
			drag.hover ??
			(() => {
				const row = document
					.elementFromPoint(event.clientX, event.clientY)
					?.closest('.schem-pin');
				return row?.dataset.componentId
					? { componentId: row.dataset.componentId, pinName: row.dataset.pinName }
					: null;
			})();
		if (drag.moved && target) {
			createWire(
				{ componentId: drag.from.componentId, pinName: drag.from.pinName },
				target
			);
		}
	}
</script>

<svelte:head>
	<title>HardcoreAI Hardware IDE</title>
</svelte:head>

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
{:else if !user}
	<section class="auth-container" in:fade={{ duration: 150 }}>
		<div class="auth-box">
			<div class="auth-header">
				<div class="logo-large"></div>
				<h2>HardcoreAI</h2>
				<p class="muted">Hardware Project IDE & Code Synthesis</p>
			</div>
			
			<form onsubmit={handleEmailAuth} class="auth-form">
				<div class="auth-toggle">
					<button 
						type="button" 
						class:active={authMode === 'login'} 
						onclick={() => setAuthMode('login')}
					>
						Sign In
					</button>
					<button 
						type="button" 
						class:active={authMode === 'register'} 
						onclick={() => setAuthMode('register')}
					>
						Register
					</button>
				</div>

				<label>
					Email Address
					<input 
						type="email" 
						bind:value={authEmail} 
						placeholder="name@example.com" 
						required 
					/>
				</label>

				<label>
					Password
					<input 
						type="password" 
						bind:value={authPassword} 
						placeholder="••••••••" 
						required 
					/>
				</label>

				<label>
					Security Check
					<div class="captcha-container">
						<div class="captcha-visual" title="Click to regenerate" onclick={generateCaptcha}>
							{#each captchaCode.split('') as char, index}
								<span style="transform: rotate({((index * 13) % 25) - 12.5}deg) translateY({((index * 7) % 8) - 4}px);">
									{char}
								</span>
							{/each}
						</div>
						<input 
							type="text" 
							bind:value={captchaInput} 
							placeholder="Enter code" 
							required 
						/>
					</div>
				</label>

				<button type="submit" class="auth-submit primary" disabled={authLoading}>
					{authLoading ? 'Please wait...' : authMode === 'login' ? 'Sign In' : 'Register'}
				</button>
			</form>

			<div class="auth-divider">
				<span>or continue with</span>
			</div>

			<button onclick={handleGoogleLogin} class="google-btn" disabled={authLoading}>
				<svg class="google-icon" viewBox="0 0 24 24" width="18" height="18">
					<path fill="#EA4335" d="M12 5.04c1.62 0 3.08.56 4.22 1.65l3.15-3.15C17.45 1.76 14.94 1 12 1 7.35 1 3.4 3.65 1.48 7.51l3.78 2.93C6.18 7.15 8.87 5.04 12 5.04z"/>
					<path fill="#4285F4" d="M23.49 12.27c0-.81-.07-1.59-.2-2.34H12v4.44h6.44c-.28 1.48-1.12 2.73-2.38 3.58l3.69 2.86c2.16-1.99 3.74-4.91 3.74-8.54z"/>
					<path fill="#FBBC05" d="M5.26 10.44C4.94 11.44 4.75 12.5 4.75 13.6c0 1.1.19 2.16.51 3.16l-3.78 2.93C.54 17.59 0 15.65 0 13.6c0-2.05.54-3.99 1.48-6.09l3.78 2.93z"/>
					<path fill="#34A853" d="M12 23c3.24 0 5.97-1.07 7.96-2.91l-3.69-2.86c-1.12.75-2.55 1.21-4.27 1.21-3.13 0-5.82-2.11-6.74-5.39L1.48 15.98C3.4 19.84 7.35 23 12 23z"/>
				</svg>
				Google
			</button>
		</div>
	</section>
{:else}
	<main class="shell">
		<header class="topbar">
			<div class="brand">
				<span class="logo" aria-hidden="true"></span>
				<div>
					<p class="eyebrow">HardcoreAI</p>
					<h1>Hardware Project IDE</h1>
				</div>
				<!-- Account circle container next to brand -->
				<div class="account-container-top">
					<button class="account-circle" onclick={toggleAccountMenu} aria-label="Account Menu">
						{user?.email?.charAt(0).toUpperCase() ?? 'U'}
					</button>
					{#if accountMenuOpen}
						<div class="account-dropdown-panel" transition:fade={{ duration: 100 }} onclick={(e) => e.stopPropagation()}>
							<div class="account-dropdown-header">
								<div class="avatar-large">{user?.email?.charAt(0).toUpperCase() ?? 'U'}</div>
								<div class="header-info">
									<strong>Developer</strong>
									<span class="email-span" title={user?.email}>{user?.email}</span>
								</div>
							</div>
							
							<div class="divider"></div>

							<form onsubmit={handleChangePassword} class="change-password-form">
								<p class="form-title">Change Password</p>
								<input 
									type="password" 
									bind:value={newPassword} 
									placeholder="New password (min 6 chars)" 
									required 
								/>
								<button type="submit" disabled={passwordLoading} class="primary mini">
									{passwordLoading ? 'Updating...' : 'Update Password'}
								</button>
							</form>

							<div class="divider"></div>

							<button class="dropdown-logout-btn" onclick={handleLogout}>
								Log Out
							</button>
						</div>
					{/if}
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
				<button
					class:active={activeView === 'emulator'}
					disabled={!selectedProject}
					onclick={() => (activeView = 'emulator')}
				>
					Emulator
				</button>
			</nav>

		<!-- Workbench actions live in the navbar so the canvas gets the full
		     panel height; they appear only while the Workbench view is open. -->
		{#if activeView === 'workbench' && selectedProject}
			<div class="nav-actions">
				<button class="nav-act" onclick={rotateSelected} disabled={!selectedIds.length}>
					{selectedIds.length > 1 ? `Rotate ${selectedIds.length}` : 'Rotate'}
				</button>
				<button
					class="nav-act"
					onclick={deleteSelected}
					disabled={!selectedIds.length && !selectedWireId}
				>
					Delete
				</button>
				<button
					class="nav-act"
					onclick={clearWorkbench}
					disabled={!workbench.placed_components.length}
				>
					Clear
				</button>
				<span class="nav-sep" aria-hidden="true"></span>
				<button class="nav-act" onclick={generateFirmware} disabled={busy}>
					{busy ? 'Working…' : 'Generate'}
				</button>
				<button class="nav-act primary" onclick={saveWorkbench} disabled={!workbenchDirty}>
					{workbenchDirty ? 'Save' : 'Saved'}
				</button>
			</div>
		{/if}

		<div class="project-chip">
			<span class="chip-name">{selectedProject?.name ?? 'No project open'}</span>
			<strong class:dirty={workbenchDirty || fileDirty}>
				{#if workbenchDirty || fileDirty}● {saveStatus}{:else}{saveStatus}{/if}
			</strong>
		</div>
	</header>



	{#if activeView === 'dashboard'}
		<section class="dashboard" in:fade={{ duration: 150 }}>
			<div class="profile-panel">
				<div class="profile-avatar-section">
					<div class="profile-avatar">
						{user?.email?.charAt(0).toUpperCase() ?? 'U'}
					</div>
					<div class="profile-details">
						<h3>Developer</h3>
						<p class="profile-email" title={user?.email ?? 'anonymous'}>{user?.email ?? 'anonymous'}</p>
					</div>
				</div>
				<div class="profile-stats">
					<div class="profile-stat-box">
						<span>Projects</span>
						<strong>{projects.length}</strong>
					</div>
					<div class="profile-stat-box">
						<span>Status</span>
						<strong style="font-size: 0.76rem; color: #74d7bb; text-transform: uppercase;">Active</strong>
					</div>
				</div>
				<div class="profile-actions">
					<p class="eyebrow" style="margin-bottom: 0.2rem; font-size: 0.68rem; letter-spacing: 0.05em;">Quick Settings</p>
					<button onclick={() => toast('Profile details sync automatically.', 'success')}>
						Status Refresh
					</button>
					<button onclick={handleLogout} class="logout-btn-profile">
						Log Out
					</button>
				</div>
			</div>

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
				<!-- Slim contextual hint strip; the action buttons now live in
				     the navbar. -->
				<div class="workbench-hint" class:wiring={pendingPin}>
					{#if pendingPin}
						Wiring from {pinLabel(pendingPin.componentId, pendingPin.pinName)} — click a
						second pin
					{:else if selectedIds.length > 1}
						{selectedIds.length} components selected · drag a pin to wire · Del removes
					{:else}
						Drag pin to pin to wire · Shift-click to multi-select · Del removes
					{/if}
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
					onclick={clearSelection}
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
										selectedIds = [];
										selectedComponentId = null;
									}}
									oncontextmenu={(event) => openWireMenu(event, wire)}
									onkeydown={(event) => {
										if (event.key === 'Enter' || event.key === ' ') selectedWireId = wire.id;
									}}
								/>
							{/if}
						{/each}

						{#if wiring && wiring.source !== 'schematic' && wiring.moved}
							{@const start = wireEndpoint(wiring.from)}
							<path
								class="wire-ghost"
								d={`M ${start.x} ${start.y} C ${start.x + 60} ${start.y}, ${
									wiring.cursor.x - 60
								} ${wiring.cursor.y}, ${wiring.cursor.x} ${wiring.cursor.y}`}
							/>
						{/if}
					</svg>

					{#each workbench.placed_components as instance (instance.id)}
						{@const def = definition(instance.definition_id)}
						{#if def}
							<div
								role="button"
								tabindex="0"
								aria-label={instance.display_name}
								class:selected={isSelected(instance.id)}
								class:primary-select={instance.id === selectedComponentId &&
									selectedIds.length > 1}
								class={componentClass(def)}
								style={`left:${instance.x}px; top:${instance.y}px; width:${def.width}px; height:${def.height}px; --rot:${instance.rotation ?? 0}deg;`}
								onpointerdown={(event) => startMove(event, instance)}
								onclick={(event) => event.stopPropagation()}
								oncontextmenu={(event) => openComponentMenu(event, instance)}
								onkeydown={(event) => {
									if (event.key === 'Enter') selectComponent(instance.id);
								}}
							>
								<div class="part-body">
									<!-- Vector "template" graphic; pins overlay on top of it. -->
									<div class="chip-art" aria-hidden="true">
										{@html background(
											def.visual_type,
											def.width,
											def.height,
											instance.config
										)}
									</div>
									<div class="part-title">
										<strong>{instance.display_name}</strong>
										<small>{def.category}</small>
									</div>
								</div>

								{#each def.pins as pin (pin.name)}
									{@const drag = pinDragState(instance.id, pin.name, pin.role)}
									<button
										data-component-id={instance.id}
										data-pin-name={pin.name}
										class:armed={pendingPin?.componentId === instance.id &&
											pendingPin?.pinName === pin.name}
										class:wired={pinIsWired(instance.id, pin.name)}
										class={`pin ${pin.side} role-${pin.role} ${drag}`}
										style={`left:${pin.x}px; top:${pin.y}px;`}
										title={`${pin.label} · ${pin.role}${
											pinIsWired(instance.id, pin.name) ? ' · wired' : ''
										}`}
										aria-label={`Pin ${pin.label}, ${pin.role}`}
										onpointerdown={(event) => startWire(event, instance, pin)}
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
					<span>
						{selectedIds.length
							? `${selectedIds.length} selected`
							: `${schematicComponents.length} parts`}
						· {workbench.wires.length} wires
					</span>
				</div>

				<!-- Interactive pin panel: every component is a foldable row of pins.
				     Drag a pin onto another pin (here or on the workbench) to wire. -->
				<div class="pin-panel">
					{#if schematicComponents.length === 0}
						<p class="muted small">Place a component to list its pins here.</p>
					{:else}
						{#each schematicComponents as instance (instance.id)}
							{@const def = definition(instance.definition_id)}
							{#if def}
								<div
									class="schem-comp"
									class:active={isSelected(instance.id)}
								>
									<button
										class="schem-comp-head"
										onclick={() => toggleSchematicFold(instance.id)}
									>
										<span class="fold" class:closed={schematicCollapsed[instance.id]}
											>▾</span
										>
										<span class={`thumb-mini ${def.thumbnail}`}></span>
										<span class="schem-comp-name">{instance.display_name}</span>
										<span class="schem-pin-count">{def.pins.length}</span>
									</button>
									{#if !schematicCollapsed[instance.id]}
										<ul class="schem-pin-list">
											{#each def.pins as pin (pin.name)}
												{@const conns = pinConnections(instance.id, pin.name)}
												{@const drag = pinDragState(
													instance.id,
													pin.name,
													pin.role
												)}
												<li>
													<button
														data-component-id={instance.id}
														data-pin-name={pin.name}
														class={`schem-pin role-${pin.role} ${drag}`}
														class:wired={conns.length > 0}
														title={`${pin.label} · ${
															ROLE_LABEL[pin.role] ?? pin.role
														} — drag to another pin to wire`}
														onpointerdown={(event) =>
															startSchematicWire(event, instance, pin)}
													>
														<span
															class="schem-pin-dot"
															style={`background:${
																conns[0]?.color ?? 'transparent'
															}`}
														></span>
														<span class="schem-pin-label">{pin.label}</span>
														<span class="schem-pin-role"
															>{ROLE_LABEL[pin.role] ?? pin.role}</span
														>
													</button>
													{#each conns as conn (conn.wireId)}
														<button
															class="schem-conn"
															class:selected={conn.wireId === selectedWireId}
															onclick={() => (selectedWireId = conn.wireId)}
															title="Select this wire"
														>
															<span
																class="schem-conn-bar"
																style={`background:${conn.color}`}
															></span>
															<span>→ {conn.label}</span>
														</button>
													{/each}
												</li>
											{/each}
										</ul>
									{/if}
								</div>
							{/if}
						{/each}
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
								<tr><td colspan="2" class="muted">Drag pin to pin to build the netlist.</td></tr>
							{/each}
						</tbody>
					</table>
				</div>

				<div class="inspector">
					<h3>Inspector</h3>
					{#if selectedIds.length > 1}
						<p><strong>{selectedIds.length} components selected</strong></p>
						<p class="muted">Rotate, move or delete them together.</p>
					{:else if selectedComponent}
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

			<AssistantPanel
				projectId={selectedProject.id}
				apiBase={API_BASE}
				token={session?.access_token}
				onstatus={(text) => setStatus(text, true)}
				ondone={onAgentDone}
			/>
		</section>
	{:else if activeView === 'code'}
		<section class="code-shell" in:fade={{ duration: 150 }}>
			<aside class="file-tree">
				<div class="section-title">
					<h2>Files</h2>
					<span>{files.length}</span>
				</div>
				<div class="file-list">
					{#each files as file (file.path)}
						<button
							class="file-btn"
							class:active={file.path === activeFilePath}
							onclick={() => (activeFilePath = file.path)}
						>
							<span>{file.path}</span>
							<small>{file.language}</small>
						</button>
					{:else}
						<p class="muted small">No files yet — generate firmware to start.</p>
					{/each}
				</div>
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
				<!-- Slim contextual hint strip, mirroring the workbench view. -->
				<div class="editor-hint" class:wiring={fileDirty}>
					{#if !activeFile}
						Select a file from the list to start coding
					{:else if fileDirty}
						Unsaved edits in {activeFilePath} — Ctrl+S to save
					{:else}
						Editing {activeFilePath} · Regenerate rebuilds from the workbench
					{/if}
				</div>

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

			<AssistantPanel
				projectId={selectedProject.id}
				apiBase={API_BASE}
				token={session?.access_token}
				onstatus={(text) => setStatus(text, true)}
				ondone={onAgentDone}
			/>
		</section>
	{:else if activeView === 'emulator'}
		<section class="code-shell" style="grid-template-columns: 200px 1fr 300px;" in:fade={{ duration: 150 }}>
			<aside class="file-tree">
				<div class="section-title">
					<h2>PlatformIO</h2>
					<span>Build Tools</span>
				</div>
				<div class="file-list" style="padding: 1rem; display: flex; flex-direction: column; gap: 0.5rem;">
					<button class="primary" style="width: 100%; justify-content: center;" onclick={runBuild} disabled={emulatorBusy}>Build Firmware</button>
					<button class="primary" style="width: 100%; justify-content: center;" onclick={runFlash} disabled={emulatorBusy}>Flash (Upload)</button>
					<button class="primary" style="width: 100%; justify-content: center;" onclick={runEmulator} disabled={emulatorBusy || qemuRunning}>Start QEMU</button>
				</div>
				<div class="component-summary">
					<h3>Status</h3>
					<p style="margin-top: 0.5rem;">{pioStatus}</p>
				</div>
			</aside>

			<section class="editor-pane" style="display: flex; flex-direction: column;">
				<div class="toolbar">
					<div class="toolbar-info">
						<strong>Emulator & Debugger</strong>
						<span>Hardware-in-the-loop simulation</span>
					</div>
					<div class="row-actions">
						<button onclick={runConnect} disabled={emulatorBusy || debuggerConnected}>
							{debuggerConnected ? 'Connected' : 'Connect Debugger'}
						</button>
						<button onclick={runHalt} disabled={!debuggerConnected || !debuggerRunning}>Halt</button>
						<button onclick={runContinue} disabled={!debuggerConnected || debuggerRunning}>Continue</button>
						<button onclick={runStep} disabled={!debuggerConnected || debuggerRunning}>Step</button>
						<button class="primary" onclick={fetchRegisters} disabled={!debuggerConnected || debuggerRunning}>Read Registers</button>
					</div>
				</div>
				
				<div style="display: flex; flex-direction: row; flex: 1; min-height: 0; gap: 1rem; padding: 1.5rem; background: #0b0e14; border-top: 1px solid #1f2937;">
					<div class="terminal" style="flex: 1; color: #52d1a4; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; overflow-y: auto; white-space: pre-wrap; line-height: 1.5;">
						{#each terminalLog as log}
							<div>{log}</div>
						{/each}
					</div>
					{#if qemuLog.length > 0 || qemuRunning}
					<div class="terminal qemu-terminal" style="flex: 1; color: #f59e0b; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; overflow-y: auto; white-space: pre-wrap; line-height: 1.5; border-left: 1px solid #1f2937; padding-left: 1rem;">
						<h4 style="color: #fff; margin-top: 0; margin-bottom: 0.5rem; text-transform: uppercase; letter-spacing: 0.05em; font-size: 0.75rem;">QEMU Serial Output</h4>
						{#each qemuLog as log}
							<div>{log}</div>
						{/each}
					</div>
					{/if}
				</div>
			</section>

			<aside class="settings-panel">
				<div class="section-title">
					<h2>Registers</h2>
					<span>Cortex-M3 State</span>
				</div>
				<div class="terminal" style="background: #111827; color: #f59e0b; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; padding: 1.5rem; border-radius: 8px; white-space: pre-wrap; margin: 1rem; border: 1px solid #1f2937; line-height: 1.8;">
					{registersData || 'Not connected'}
				</div>
			</aside>
		</section>
	{/if}
</main>
{/if}

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

	/* ---- topbar ----
	   Flex row so the optional workbench action group can appear or vanish
	   without a fixed grid template breaking. brand stays left, project chip
	   right; nav + actions sit in the middle. */
	.topbar {
		display: flex;
		align-items: center;
		gap: 1rem;
		padding: 0.7rem 1.25rem;
		border-bottom: 1px solid #2b333d;
		background: #11151b;
		position: sticky;
		top: 0;
		z-index: 20;
	}

	.topbar .brand {
		flex: 1 1 auto;
		min-width: 0;
	}

	.topbar .project-chip {
		flex: 1 1 auto;
		min-width: 0;
	}

	/* ---- workbench actions in the navbar ---- */
	.nav-actions {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		flex-wrap: nowrap;
	}

	.nav-act {
		border-color: #343c46;
		background: #1a1f27;
		padding: 0.4rem 0.7rem;
		font-size: 0.82rem;
		white-space: nowrap;
	}

	.nav-act.primary {
		border-color: #4eb79a;
		background: #1f7a65;
		color: #eafff8;
	}

	.nav-act.primary:hover:not(:disabled) {
		background: #258b73;
	}

	.nav-sep {
		width: 1px;
		height: 22px;
		background: #2b333d;
		margin: 0 0.2rem;
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
		grid-template-columns: 260px minmax(300px, 350px) 1fr;
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

	/* ---- IDE grid ----
	   Three columns: a left bar that stacks Components over Schematic, the
	   Workbench in the middle, and the AI agent chat panel on the right.
	   The left column is split into two rows; the middle and right span both. */
	.ide-grid {
		display: grid;
		grid-template-columns: 300px minmax(420px, 1fr) 340px;
		grid-template-rows: minmax(0, 1fr) minmax(0, 1fr);
		gap: 1rem;
	}

	/* DOM order is palette, workbench, schematic, assistant — each child is
	   pinned to its cell so the visual layout is independent of source order. */
	.ide-grid .palette {
		grid-column: 1;
		grid-row: 1;
	}
	.ide-grid .schema {
		grid-column: 1;
		grid-row: 2;
	}
	.ide-grid .workbench-panel {
		grid-column: 2;
		grid-row: 1 / span 2;
	}
	.ide-grid > :global(.assistant) {
		grid-column: 3;
		grid-row: 1 / span 2;
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
		/* title · pin panel (flexes + scrolls) · netlist · inspector */
		grid-template-rows: auto 1fr auto auto;
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
		gap: 0.6rem;
		min-height: 0;
		height: 100%;
	}

	/* Slim contextual hint above the canvas — replaces the old toolbar card
	   now that the action buttons have moved into the navbar. */
	.workbench-hint {
		padding: 0.4rem 0.7rem;
		font-size: 0.76rem;
		color: #8e9aaa;
		background: #11151b;
		border: 1px solid #2b333d;
		border-radius: 8px;
	}

	.workbench-hint.wiring {
		color: #74d7bb;
		border-color: #2f6b5c;
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

	.wire-layer path:not(.wire-ghost):hover {
		stroke-width: 5.5;
	}

	.wire-layer path.selected {
		stroke-width: 7;
		filter: drop-shadow(0 0 7px currentColor);
	}

	/* in-progress drag-wire preview */
	.wire-layer path.wire-ghost {
		fill: none;
		stroke: #74d7bb;
		stroke-width: 3;
		stroke-dasharray: 7 5;
		stroke-linecap: round;
		pointer-events: none;
		opacity: 0.9;
	}

	/* ---- chip vector template ---- */
	.chip-art {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
		pointer-events: none;
		z-index: 0;
	}

	.chip-art :global(svg.chip-symbol) {
		display: block;
		width: 100%;
		height: 100%;
	}

	/* ---- schematic pin panel ---- */
	.pin-panel {
		display: grid;
		align-content: start;
		gap: 0.4rem;
		overflow-y: auto;
		min-height: 0;
		padding-right: 0.2rem;
	}

	.schem-comp {
		border: 1px solid #2b333d;
		background: #171c23;
		border-radius: 8px;
		overflow: hidden;
	}

	.schem-comp.active {
		border-color: #2f6b5c;
	}

	.schem-comp-head {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		width: 100%;
		border: none;
		border-radius: 0;
		background: #1c2330;
		padding: 0.45rem 0.55rem;
		text-align: left;
	}

	.schem-comp-head:hover:not(:disabled) {
		background: #232c3a;
	}

	.fold {
		font-size: 0.7rem;
		color: #8e9aaa;
		transition: transform 0.12s ease;
	}

	.fold.closed {
		transform: rotate(-90deg);
	}

	.thumb-mini {
		width: 22px;
		height: 16px;
		border: 1px solid #3d4653;
		border-radius: 4px;
		background: #27313d;
		flex-shrink: 0;
	}
	.thumb-mini.board {
		background: linear-gradient(90deg, #244e8f 0 72%, #b8c4cf 72% 88%, #11151b 88%);
	}
	.thumb-mini.motor {
		border-radius: 50%;
		background: radial-gradient(circle, #d7dde5 0 38%, #6b7787 39% 58%, #222832 59%);
	}
	.thumb-mini.driver {
		background: repeating-linear-gradient(90deg, #233044 0 4px, #18202a 4px 8px);
	}
	.thumb-mini.led {
		background: radial-gradient(circle, #ff667a 0 28%, #55242c 29% 58%, #171c23 59%);
	}
	.thumb-mini.resistor {
		background: linear-gradient(90deg, #9ca3af 0 20%, #d8b76a 20% 80%, #9ca3af 80%);
	}
	.thumb-mini.battery {
		background: linear-gradient(180deg, #5a606b, #202630);
	}

	.schem-comp-name {
		flex: 1;
		font-size: 0.8rem;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.schem-pin-count {
		font-size: 0.66rem;
		color: #8e9aaa;
		background: #11151b;
		border-radius: 10px;
		padding: 0.05rem 0.4rem;
	}

	.schem-pin-list {
		list-style: none;
		margin: 0;
		padding: 0.3rem;
		display: grid;
		gap: 0.2rem;
	}

	.schem-pin {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		width: 100%;
		border: 1px solid #2b333d;
		border-radius: 6px;
		background: #11151b;
		padding: 0.32rem 0.45rem;
		text-align: left;
		cursor: grab;
		touch-action: none;
	}

	.schem-pin:active {
		cursor: grabbing;
	}

	.schem-pin:hover {
		border-color: #45505d;
	}

	.schem-pin-dot {
		width: 9px;
		height: 9px;
		border-radius: 50%;
		border: 1px solid #3d4653;
		flex-shrink: 0;
	}

	.schem-pin-label {
		flex: 1;
		font-size: 0.76rem;
		font-weight: 700;
	}

	.schem-pin-role {
		font-size: 0.62rem;
		text-transform: uppercase;
		letter-spacing: 0.03em;
		color: #8e9aaa;
	}

	/* role accent stripe on the left of a schematic pin row */
	.schem-pin.role-power {
		border-left: 3px solid #f6c560;
	}
	.schem-pin.role-ground {
		border-left: 3px solid #8995a4;
	}
	.schem-pin.role-pwm {
		border-left: 3px solid #a78bfa;
	}
	.schem-pin.role-motor {
		border-left: 3px solid #f59e0b;
	}
	.schem-pin.role-input {
		border-left: 3px solid #60a5fa;
	}
	.schem-pin.role-output {
		border-left: 3px solid #52d1a4;
	}
	.schem-pin.role-gpio {
		border-left: 3px solid #e7edf4;
	}
	.schem-pin.role-passive {
		border-left: 3px solid #c7cfd9;
	}

	.schem-pin.wired {
		background: #15211f;
	}

	/* live drag-target highlight, shared by workbench + schematic pins */
	.schem-pin.compat-ideal,
	.pin.compat-ideal {
		box-shadow: 0 0 0 2px #52d1a4, 0 0 10px rgb(82 209 164 / 0.5);
	}
	.schem-pin.compat-ok,
	.pin.compat-ok {
		box-shadow: 0 0 0 2px #f6c560, 0 0 10px rgb(246 197 96 / 0.45);
	}
	.schem-pin.compat-warn,
	.pin.compat-warn {
		box-shadow: 0 0 0 2px #f87171, 0 0 9px rgb(248 113 113 / 0.4);
		opacity: 0.78;
	}
	.schem-pin.compat-self,
	.pin.compat-self {
		opacity: 0.45;
	}

	.schem-conn {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		width: 100%;
		border: none;
		border-radius: 5px;
		background: transparent;
		padding: 0.18rem 0.45rem 0.18rem 1.4rem;
		text-align: left;
		font-size: 0.7rem;
		color: #9aa6b5;
	}

	.schem-conn:hover {
		background: #161d24;
	}

	.schem-conn.selected {
		background: #17342f;
		color: #d4dce5;
	}

	.schem-conn-bar {
		width: 14px;
		height: 3px;
		border-radius: 2px;
		flex-shrink: 0;
	}

	/* ---- workbench pin states ---- */
	.pin.wired {
		box-shadow: 0 0 0 2px rgb(116 215 187 / 0.55);
	}

	.netlist {
		display: grid;
		grid-template-rows: auto auto;
		gap: 0.4rem;
		min-height: 0;
		/* Capped so the pin panel above keeps the flexible space. */
		max-height: 28vh;
		overflow-y: auto;
		align-content: start;
		border-top: 1px solid #2b333d;
		padding-top: 0.6rem;
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
		/* files · editor · project settings · AI agent panel */
		grid-template-columns: 230px minmax(420px, 1fr) 260px 320px;
		grid-template-rows: 100%;
		gap: 1rem;
	}

	/* Mirror the workbench's .palette / .schema framing: a fixed section-title
	   row, a flexible scrolling body, then pinned sub-sections — the panel
	   itself never scrolls. */
	.file-tree {
		display: grid;
		grid-template-rows: auto 1fr auto;
		gap: 0.7rem;
		padding: 1rem;
		min-height: 0;
		height: 100%;
		overflow: hidden;
	}

	.settings-panel {
		display: grid;
		align-content: start;
		gap: 0.7rem;
		padding: 1rem;
		min-height: 0;
		height: 100%;
		overflow-y: auto;
	}

	/* Scrolling file list, like the workbench's .component-list. */
	.file-list {
		display: grid;
		align-content: start;
		gap: 0.45rem;
		overflow-y: auto;
		min-height: 0;
		padding-right: 0.2rem;
	}

	.file-btn {
		display: flex;
		justify-content: space-between;
		gap: 0.75rem;
		text-align: left;
		align-items: center;
		padding: 0.55rem 0.65rem;
	}

	.file-btn small {
		color: #74d7bb;
		text-transform: uppercase;
		font-size: 0.62rem;
	}

	.component-summary {
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
		/* hint strip · toolbar · editor — matching the workbench panel layout */
		grid-template-rows: auto auto 1fr;
		gap: 0.6rem;
		height: 100%;
	}

	/* Slim contextual hint above the editor — shares the workbench-hint look. */
	.editor-hint {
		padding: 0.4rem 0.7rem;
		font-size: 0.76rem;
		color: #8e9aaa;
		background: #11151b;
		border: 1px solid #2b333d;
		border-radius: 8px;
	}

	.editor-hint.wiring {
		color: #f5b95c;
		border-color: #7a5a26;
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
	/* Below ~1580px the four-column Code grid is cramped: drop its AI panel to
	   a full-width row beneath the rest. The Workbench grid (one left bar, a
	   wide canvas, one right panel) stays comfortable down to the 1180px
	   single-column breakpoint, so it needs no intermediate rule. */
	@media (max-width: 1580px) and (min-width: 1181px) {
		.code-shell {
			grid-template-columns: 230px minmax(420px, 1fr) 260px;
			grid-template-rows: 1fr auto;
		}
		.code-shell > :global(.assistant) {
			grid-column: 1 / -1;
		}
	}

	@media (max-width: 1180px) {
		.dashboard,
		.ide-grid,
		.code-shell {
			grid-template-columns: 1fr;
		}

		/* Single column: clear the explicit column/row pins and the two-row
		   template so every panel simply stacks in source order. */
		.ide-grid {
			grid-template-rows: none;
			grid-auto-rows: auto;
		}
		.ide-grid > :global(.assistant),
		.ide-grid .palette,
		.ide-grid .schema,
		.ide-grid .workbench-panel {
			grid-column: auto;
			grid-row: auto;
		}

		/* Narrow: let the topbar wrap so brand + chip share the top line and
		   nav / actions flow onto the next. */
		.topbar {
			flex-wrap: wrap;
		}
		.topbar nav,
		.nav-actions {
			order: 3;
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

	/* ---- auth screen ---- */
	.auth-container {
		display: grid;
		place-items: center;
		min-height: 100vh;
		min-height: 100dvh;
		background: radial-gradient(circle at center, #1b2330 0%, #0d1014 100%);
		padding: 1.5rem;
	}

	.auth-box {
		width: 100%;
		max-width: 400px;
		background: #11151b;
		border: 1px solid #2b333d;
		border-radius: 12px;
		padding: 2.2rem 2rem;
		box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
		display: grid;
		gap: 1.5rem;
	}

	.auth-header {
		text-align: center;
		display: grid;
		gap: 0.4rem;
	}

	.logo-large {
		width: 48px;
		height: 48px;
		border-radius: 12px;
		background: linear-gradient(135deg, #74d7bb, #1f7a65);
		box-shadow: 0 0 24px rgb(116 215 187 / 0.45);
		margin: 0 auto 0.75rem auto;
	}

	.auth-header h2 {
		font-size: 1.6rem;
		font-weight: 800;
		color: #eef3f8;
	}

	.auth-form {
		display: grid;
		gap: 1.1rem;
	}

	.auth-toggle {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.4rem;
		background: #0d1014;
		padding: 0.2rem;
		border-radius: 8px;
		border: 1px solid #232b35;
	}

	.auth-toggle button {
		border: none;
		background: transparent;
		padding: 0.45rem;
		font-size: 0.85rem;
		font-weight: 600;
		color: #8e9aaa;
	}

	.auth-toggle button.active {
		background: #171c23;
		border: 1px solid #2b333d;
		color: #74d7bb;
	}

	.auth-submit {
		margin-top: 0.5rem;
		font-weight: 600;
		font-size: 0.9rem;
	}

	.auth-divider {
		display: flex;
		align-items: center;
		text-align: center;
		color: #5d6877;
		font-size: 0.76rem;
	}

	.auth-divider::before,
	.auth-divider::after {
		content: '';
		flex: 1;
		border-bottom: 1px solid #232b35;
	}

	.auth-divider:not(:empty)::before {
		margin-right: .5em;
	}

	.auth-divider:not(:empty)::after {
		margin-left: .5em;
	}

	.google-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.6rem;
		border-color: #2b333d;
		background: #171c23;
		color: #eef3f8;
		font-weight: 600;
		font-size: 0.88rem;
		padding: 0.55rem;
	}

	.google-btn:hover {
		background: #232b36;
		border-color: #3b4654;
	}

	.google-icon {
		flex-shrink: 0;
	}
	
	.logout-btn {
		font-size: 0.78rem;
		font-weight: 600;
		padding: 0.35rem 0.6rem;
		background: #1c1c1f;
		border-color: #2b2b30;
		color: #aeb8c6;
	}
	
	.logout-btn:hover {
		background: #2b2224;
		border-color: #66222b;
		color: #ffb4bf;
	}

	/* ---- captcha styles ---- */
	.captcha-container {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0.8rem;
		align-items: center;
		margin-top: 0.2rem;
	}

	.captcha-visual {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.35rem;
		background: repeating-linear-gradient(
			45deg,
			#141923,
			#141923 4px,
			#0f121a 4px,
			#0f121a 8px
		);
		border: 1px dashed #3d4653;
		padding: 0.5rem 0.95rem;
		border-radius: 6px;
		font-family: 'Courier New', Courier, monospace;
		font-weight: 800;
		font-size: 1.25rem;
		letter-spacing: 0.12rem;
		color: #74d7bb;
		cursor: pointer;
		user-select: none;
		min-width: 110px;
		height: 38px;
		box-sizing: border-box;
	}

	.captcha-visual span {
		display: inline-block;
		text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.9);
	}

	/* ---- profile panel dashboard ---- */
	.profile-panel {
		display: grid;
		gap: 1.2rem;
		padding: 1.1rem;
		align-content: start;
		background: #11151b;
		border: 1px solid #2b333d;
		border-radius: 10px;
		overflow-y: auto;
		height: fit-content;
	}

	.profile-avatar-section {
		display: flex;
		align-items: center;
		gap: 0.9rem;
	}

	.profile-avatar {
		width: 48px;
		height: 48px;
		border-radius: 50%;
		background: linear-gradient(135deg, #74d7bb, #1f7a65);
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 1.35rem;
		font-weight: 800;
		color: #ffffff;
		box-shadow: 0 0 16px rgb(116 215 187 / 0.25);
		flex-shrink: 0;
	}

	.profile-details {
		display: grid;
		gap: 0.15rem;
		min-width: 0;
	}

	.profile-details h3 {
		font-size: 0.95rem;
		font-weight: 700;
		color: #eef3f8;
	}

	.profile-email {
		font-size: 0.78rem;
		color: #8e9aaa;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.profile-stats {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.6rem;
		background: #0d1014;
		padding: 0.65rem 0.55rem;
		border-radius: 8px;
		border: 1px solid #232b35;
	}

	.profile-stat-box {
		text-align: center;
		display: grid;
		gap: 0.1rem;
	}

	.profile-stat-box span {
		display: block;
		font-size: 0.64rem;
		color: #71808f;
		text-transform: uppercase;
		font-weight: 600;
		letter-spacing: 0.03em;
	}

	.profile-stat-box strong {
		font-size: 1.15rem;
		color: #74d7bb;
	}

	.profile-actions {
		display: grid;
		gap: 0.45rem;
		border-top: 1px solid #232b35;
		padding-top: 1rem;
	}

	.profile-actions button {
		text-align: left;
		padding: 0.45rem 0.65rem;
		font-size: 0.8rem;
		font-weight: 600;
		border: 1px solid #2b333d;
		background: #171c23;
		color: #aeb8c6;
		border-radius: 6px;
		transition: all 0.1s ease;
		cursor: pointer;
	}

	.profile-actions button:hover {
		background: #232b36;
		color: #eef3f8;
		border-color: #3b4654;
	}

	.profile-actions .logout-btn-profile {
		border-color: #55242c;
		background: #201317;
		color: #ffb4bf;
	}

	.profile-actions .logout-btn-profile:hover {
		background: #2f171f;
		border-color: #7a2b37;
		color: #ffe4e8;
	}

	/* ---- account dropdown overlay styles ---- */
	.account-container-top {
		position: relative;
		display: inline-block;
		margin-left: 0.8rem;
	}

	.account-circle {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		background: linear-gradient(135deg, #74d7bb, #1f7a65);
		border: 1px solid #3d4653;
		color: #ffffff;
		font-weight: 800;
		font-size: 0.85rem;
		display: flex;
		align-items: center;
		justify-content: center;
		cursor: pointer;
		padding: 0;
		box-shadow: 0 0 10px rgb(116 215 187 / 0.2);
		transition: transform 0.12s ease, box-shadow 0.12s ease;
	}

	.account-circle:hover {
		transform: scale(1.05);
		box-shadow: 0 0 14px rgb(116 215 187 / 0.4);
		border-color: #74d7bb;
	}

	.account-dropdown-panel {
		position: absolute;
		top: calc(100% + 10px);
		left: 0;
		width: 260px;
		background: #11151b;
		border: 1px solid #2b333d;
		border-radius: 10px;
		padding: 1.1rem;
		box-shadow: 0 10px 25px rgba(0, 0, 0, 0.6);
		z-index: 100;
		display: grid;
		gap: 0.85rem;
		text-align: left;
	}

	.account-dropdown-header {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.avatar-large {
		width: 38px;
		height: 38px;
		border-radius: 50%;
		background: linear-gradient(135deg, #74d7bb, #1f7a65);
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 1.1rem;
		font-weight: 800;
		color: #ffffff;
	}

	.header-info {
		display: grid;
		gap: 0.1rem;
		min-width: 0;
	}

	.header-info strong {
		font-size: 0.88rem;
		color: #eef3f8;
	}

	.header-info .email-span {
		font-size: 0.76rem;
		color: #8e9aaa;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.account-dropdown-panel .divider {
		height: 1px;
		background: #232b35;
		margin: 0 -1.1rem;
	}

	.change-password-form {
		display: grid;
		gap: 0.55rem;
	}

	.change-password-form .form-title {
		font-size: 0.72rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #74d7bb;
		margin: 0;
	}

	.change-password-form input {
		padding: 0.45rem 0.55rem;
		font-size: 0.8rem;
		border-radius: 6px;
		background: #0d1014;
		border: 1px solid #2b333d;
	}

	.change-password-form button.mini {
		padding: 0.4rem 0.6rem;
		font-size: 0.78rem;
		font-weight: 600;
		border-radius: 6px;
	}

	.dropdown-logout-btn {
		width: 100%;
		text-align: left;
		padding: 0.45rem 0.65rem;
		font-size: 0.8rem;
		font-weight: 600;
		border: 1px solid #55242c;
		background: #201317;
		color: #ffb4bf;
		border-radius: 6px;
		transition: all 0.1s ease;
		cursor: pointer;
	}

	.dropdown-logout-btn:hover {
		background: #2f171f;
		border-color: #7a2b37;
		color: #ffe4e8;
	}
</style>
