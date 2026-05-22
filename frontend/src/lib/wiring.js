/* wiring.js
 * ---------------------------------------------------------------------------
 * Pin-to-pin connection rules for the workbench.
 *
 * Policy: warn-but-allow. A connection is never *blocked* by these rules —
 * prototyping should stay flexible — but the UI uses `compatibility()` to
 * highlight sensible targets while dragging, and `connectionWarning()` to
 * raise a toast when a questionable wire is actually made.
 *
 * Pin roles come from the database (`pins.role`): one of
 *   gpio · power · ground · pwm · motor · input · output · passive
 */

/** Human-readable role labels, for badges and warnings. */
export const ROLE_LABEL = {
	gpio: 'GPIO',
	power: 'Power',
	ground: 'Ground',
	pwm: 'PWM',
	motor: 'Motor',
	input: 'Input',
	output: 'Output',
	passive: 'Passive'
};

/** Accent colour per role — mirrors the .pin.role-* classes in chip_styles. */
export const ROLE_COLOR = {
	gpio: '#e7edf4',
	power: '#f6c560',
	ground: '#8995a4',
	pwm: '#a78bfa',
	motor: '#f59e0b',
	input: '#60a5fa',
	output: '#52d1a4',
	passive: '#c7cfd9'
};

/* Signal-class buckets. Two pins are "ideal" partners when their roles sit in
 * a pair that physically makes sense; "ok" when plausible; otherwise "warn".
 *
 * Each entry is an unordered role pair. Anything not listed is "warn" — still
 * allowed, just flagged.
 */
const IDEAL_PAIRS = [
	['gpio', 'input'], //  MCU drives a driver/LED input
	['gpio', 'gpio'], //   board-to-board signal
	['pwm', 'pwm'], //     PWM source to an enable pin
	['pwm', 'input'], //   PWM into a logic input
	['gpio', 'pwm'], //    a GPIO timer pin used as PWM
	['output', 'motor'], // driver output to a motor terminal
	['output', 'input'], // chained logic
	['power', 'power'], //  rail to rail
	['ground', 'ground'], // common ground
	['passive', 'passive'], // resistor in series
	['passive', 'input'], //  resistor feeding a signal pin
	['passive', 'gpio'],
	['passive', 'output'],
	['passive', 'ground']
];

/* Plausible but worth a glance — e.g. powering a logic input directly. */
const OK_PAIRS = [
	['power', 'input'],
	['power', 'gpio'],
	['power', 'motor'],
	['ground', 'input'],
	['ground', 'gpio'],
	['ground', 'output'],
	['output', 'output'], // tying outputs is usually wrong, but allow as "ok"
	['motor', 'motor'],
	['power', 'passive'],
	['gpio', 'output']
];

function pairKey(a, b) {
	return [a, b].sort().join('|');
}

const IDEAL = new Set(IDEAL_PAIRS.map(([a, b]) => pairKey(a, b)));
const OK = new Set(OK_PAIRS.map(([a, b]) => pairKey(a, b)));

/**
 * Classify a prospective connection between two pin roles.
 * @returns {'ideal'|'ok'|'warn'}
 */
export function compatibility(roleA, roleB) {
	const key = pairKey(roleA ?? 'gpio', roleB ?? 'gpio');
	if (IDEAL.has(key)) return 'ideal';
	if (OK.has(key)) return 'ok';
	return 'warn';
}

/**
 * A warning string for a finished connection, or null when it looks fine.
 * Used to decide whether to raise a toast after a wire is created.
 */
export function connectionWarning(roleA, roleB) {
	const level = compatibility(roleA, roleB);
	if (level === 'ideal' || level === 'ok') return null;
	const a = ROLE_LABEL[roleA] ?? roleA ?? 'pin';
	const b = ROLE_LABEL[roleB] ?? roleB ?? 'pin';

	// A few specific, high-value warnings; otherwise a generic one.
	const key = pairKey(roleA, roleB);
	if (key === pairKey('power', 'ground'))
		return 'Power tied directly to ground — this is a short circuit.';
	if (key === pairKey('power', 'output'))
		return 'Power rail wired to a driver output — check this is intended.';
	if (key === pairKey('motor', 'power') || key === pairKey('motor', 'ground'))
		return 'Motor terminal wired straight to a rail — usually it goes through a driver.';
	return `Unusual connection: ${a} → ${b}. Allowed, but double-check it.`;
}

/**
 * Whether two pins may even be considered for a wire at all. The only hard
 * rule: a pin cannot connect to itself. (Same-component pins are allowed —
 * e.g. tying two grounds.)
 */
export function canConnect(endpointA, endpointB) {
	if (!endpointA || !endpointB) return false;
	return !(
		endpointA.componentId === endpointB.componentId &&
		endpointA.pinName === endpointB.pinName
	);
}
