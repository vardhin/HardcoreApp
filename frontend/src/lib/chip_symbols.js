/* chip_symbols.js
 * ---------------------------------------------------------------------------
 * Vector "template" graphics for each component `visual_type`. These render
 * as the background of a placed part; the pin buttons (from the database)
 * overlay on top, so the SVG is purely a visualisation aid.
 *
 * Why hand-authored SVG instead of traced photos:
 *   A wiring tool needs the pin anchor points to be exact. Tracing a raster
 *   product photo (potrace/autotrace) yields messy paths and zero pin data,
 *   so the pins must be placed by hand regardless. These symbols ARE that
 *   hand-placement step — clean, desaturated, scalable outlines that read as
 *   the real part without copying a copyrighted photo.
 *
 * Each symbol is a function (w, h) -> SVG inner markup, drawn in the part's
 * own coordinate space (0..w, 0..h) so it scales with the catalogue
 * width/height. `background()` returns the full <svg> wrapper.
 *
 * Drop-in traced images:
 *   If you later want an actual traced PNG/SVG silhouette, set
 *   `component.config.template_url` on the instance — `background()` honours
 *   it and renders the image instead, still desaturated, pins still on top.
 */

// Shared palette — deliberately desaturated so it reads as a "template".
const C = {
	body: '#2b333f',
	bodyLight: '#39424f',
	stroke: '#6b7787',
	strokeSoft: '#4a5563',
	silk: '#8d99a8', // silkscreen text / fine detail
	metal: '#aab4c0',
	metalDark: '#7c8794',
	accent: '#5b6675'
};

/* ---- per-visual_type symbol builders -------------------------------------
 * All coordinates are relative to the part box (0,0)-(w,h).
 */
const SYMBOLS = {
	/* STM32 Blue Pill: PCB rectangle, USB tab, MCU QFP, crystal, headers. */
	'blue-pill'(w, h) {
		const railTop = 18;
		const railBot = h - 18;
		return `
			<rect x="3" y="3" width="${w - 6}" height="${h - 6}" rx="9"
				fill="${C.body}" stroke="${C.stroke}" stroke-width="1.5"/>
			<!-- USB tab -->
			<rect x="${w / 2 - 26}" y="-6" width="52" height="20" rx="3"
				fill="${C.metal}" stroke="${C.metalDark}" stroke-width="1"/>
			<!-- header rails -->
			<line x1="10" y1="${railTop}" x2="10" y2="${railBot}"
				stroke="${C.strokeSoft}" stroke-width="2"/>
			<line x1="${w - 10}" y1="${railTop}" x2="${w - 10}" y2="${railBot}"
				stroke="${C.strokeSoft}" stroke-width="2"/>
			<!-- MCU QFP package -->
			<rect x="${w / 2 - 34}" y="${h / 2 - 34}" width="68" height="68" rx="4"
				fill="#1a1f27" stroke="${C.accent}" stroke-width="1.5"/>
			<circle cx="${w / 2 - 22}" cy="${h / 2 - 22}" r="4" fill="none"
				stroke="${C.silk}" stroke-width="1"/>
			<!-- QFP lead combs -->
			${comb(w / 2 - 34, h / 2 - 34, 68, 'h', C.metalDark, -5)}
			${comb(w / 2 - 34, h / 2 + 34, 68, 'h', C.metalDark, 5)}
			${comb(w / 2 - 34, h / 2 - 34, 68, 'v', C.metalDark, -5)}
			${comb(w / 2 + 34, h / 2 - 34, 68, 'v', C.metalDark, 5)}
			<!-- crystal -->
			<rect x="${w / 2 - 20}" y="${h - 56}" width="40" height="14" rx="7"
				fill="${C.metal}" stroke="${C.metalDark}" stroke-width="1"/>
			<!-- reset button -->
			<rect x="${w - 30}" y="${h - 40}" width="16" height="12" rx="2"
				fill="${C.bodyLight}" stroke="${C.strokeSoft}" stroke-width="1"/>
		`;
	},

	/* L298N driver: PCB with the big H-bridge IC and the finned heat sink. */
	driver(w, h) {
		return `
			<rect x="3" y="3" width="${w - 6}" height="${h - 6}" rx="7"
				fill="${C.body}" stroke="${C.stroke}" stroke-width="1.5"/>
			<!-- Multiwatt IC body -->
			<rect x="${w * 0.18}" y="${h / 2 - 22}" width="${w * 0.38}" height="44" rx="3"
				fill="#1a1f27" stroke="${C.accent}" stroke-width="1.5"/>
			<text x="${w * 0.37}" y="${h / 2 + 4}" font-size="9" fill="${C.silk}"
				text-anchor="middle" font-family="monospace">L298</text>
			${comb(w * 0.18, h / 2 + 22, w * 0.38, 'h', C.metalDark, 5)}
			<!-- heat sink fins -->
			<g>
				${Array.from({ length: 5 }, (_, i) =>
					`<rect x="${w * 0.62 + i * 7}" y="14" width="3.4" height="${h - 28}"
						fill="${C.metal}" stroke="${C.metalDark}" stroke-width="0.6"/>`
				).join('')}
			</g>
			<!-- screw terminals -->
			${screwTerminals(10, h - 14, 3)}
		`;
	},

	/* DC motor: cylindrical can, end-bell, output shaft. */
	motor(w, h) {
		const r = Math.min(w, h) * 0.42;
		const cx = w * 0.42;
		const cy = h / 2;
		return `
			<circle cx="${cx}" cy="${cy}" r="${r}"
				fill="${C.body}" stroke="${C.stroke}" stroke-width="1.5"/>
			<circle cx="${cx}" cy="${cy}" r="${r * 0.62}" fill="none"
				stroke="${C.strokeSoft}" stroke-width="1.5"/>
			<circle cx="${cx}" cy="${cy}" r="${r * 0.22}" fill="${C.metalDark}"/>
			<!-- shaft -->
			<rect x="${cx + r}" y="${cy - 4}" width="${w - cx - r - 2}" height="8" rx="3"
				fill="${C.metal}" stroke="${C.metalDark}" stroke-width="1"/>
			<!-- vent slots on the can -->
			${Array.from({ length: 3 }, (_, i) =>
				`<line x1="${cx - r * 0.5}" y1="${cy - 10 + i * 10}"
					x2="${cx + r * 0.5}" y2="${cy - 10 + i * 10}"
					stroke="${C.strokeSoft}" stroke-width="1"/>`
			).join('')}
		`;
	},

	/* LED: domed lens with a hint of the internal anvil/post. */
	led(w, h) {
		const cx = w / 2;
		const cy = h * 0.46;
		const r = Math.min(w, h) * 0.34;
		return `
			<path d="M ${cx - r} ${cy + r}
				A ${r} ${r} 0 1 1 ${cx + r} ${cy + r} Z"
				fill="${C.body}" stroke="${C.stroke}" stroke-width="1.5"/>
			<ellipse cx="${cx - r * 0.3}" cy="${cy - r * 0.3}" rx="${r * 0.3}" ry="${r * 0.2}"
				fill="${C.bodyLight}" opacity="0.8"/>
			<!-- internal post + anvil -->
			<rect x="${cx - 2}" y="${cy}" width="4" height="${r + h * 0.2}" fill="${C.metalDark}"/>
			<path d="M ${cx + 4} ${cy + 4} l 7 0 l 0 ${r}" fill="none"
				stroke="${C.metalDark}" stroke-width="2.5"/>
		`;
	},

	/* Resistor: axial body with four colour bands rendered in grey tones. */
	resistor(w, h) {
		const bx = w * 0.22;
		const bw = w * 0.56;
		const by = h / 2 - 11;
		const band = (frac, ww, fill) =>
			`<rect x="${bx + bw * frac}" y="${by}" width="${ww}" height="22" fill="${fill}"/>`;
		return `
			<!-- leads -->
			<line x1="0" y1="${h / 2}" x2="${bx}" y2="${h / 2}"
				stroke="${C.metalDark}" stroke-width="2.5"/>
			<line x1="${bx + bw}" y1="${h / 2}" x2="${w}" y2="${h / 2}"
				stroke="${C.metalDark}" stroke-width="2.5"/>
			<!-- body -->
			<rect x="${bx}" y="${by}" width="${bw}" height="22" rx="11"
				fill="${C.body}" stroke="${C.stroke}" stroke-width="1.5"/>
			${band(0.12, 4, C.metalDark)}
			${band(0.32, 4, C.silk)}
			${band(0.52, 4, C.metalDark)}
			${band(0.78, 4, C.accent)}
		`;
	},

	/* 9V battery: prismatic cell with the two snap terminals on top. */
	battery(w, h) {
		return `
			<rect x="6" y="14" width="${w - 12}" height="${h - 18}" rx="6"
				fill="${C.body}" stroke="${C.stroke}" stroke-width="1.5"/>
			<rect x="${w * 0.2}" y="6" width="${w * 0.6}" height="10" rx="3"
				fill="${C.bodyLight}" stroke="${C.strokeSoft}" stroke-width="1"/>
			<!-- snap terminals -->
			<circle cx="${w * 0.36}" cy="6" r="6" fill="${C.metal}" stroke="${C.metalDark}"/>
			<rect x="${w * 0.58}" y="0" width="12" height="12" rx="2"
				fill="${C.metal}" stroke="${C.metalDark}"/>
			<line x1="14" y1="${h * 0.5}" x2="${w - 14}" y2="${h * 0.5}"
				stroke="${C.strokeSoft}" stroke-width="1"/>
		`;
	},

	/* Fallback for any visual_type without a dedicated symbol. */
	generic(w, h) {
		return `
			<rect x="3" y="3" width="${w - 6}" height="${h - 6}" rx="7"
				fill="${C.body}" stroke="${C.stroke}" stroke-width="1.5"/>
			<rect x="${w * 0.5 - 16}" y="${h * 0.5 - 16}" width="32" height="32" rx="4"
				fill="#1a1f27" stroke="${C.accent}" stroke-width="1.5"/>
		`;
	}
};

/* A row/column of IC leads (the comb on a chip edge). `dir` h|v, `out` is
 * the perpendicular offset the leads stick out by (sign = direction). */
function comb(x, y, span, dir, fill, out) {
	const n = Math.max(3, Math.round(span / 9));
	const step = span / n;
	let s = '';
	for (let i = 0; i < n; i++) {
		if (dir === 'h') {
			const lx = x + step * (i + 0.5);
			s += `<rect x="${lx - 1.4}" y="${y}" width="2.8" height="${Math.abs(out)}"
				transform="translate(0 ${out < 0 ? out : 0})" fill="${fill}"/>`;
		} else {
			const ly = y + step * (i + 0.5);
			s += `<rect x="${x}" y="${ly - 1.4}" width="${Math.abs(out)}" height="2.8"
				transform="translate(${out < 0 ? out : 0} 0)" fill="${fill}"/>`;
		}
	}
	return s;
}

/* A strip of green-terminal-block screw terminals along a bottom edge. */
function screwTerminals(x, y, count) {
	let s = '';
	for (let i = 0; i < count; i++) {
		const tx = x + i * 22;
		s += `<rect x="${tx}" y="${y - 12}" width="18" height="14" rx="2"
			fill="${C.bodyLight}" stroke="${C.strokeSoft}" stroke-width="1"/>
			<circle cx="${tx + 9}" cy="${y - 5}" r="3.4" fill="none"
				stroke="${C.metalDark}" stroke-width="1.4"/>
			<line x1="${tx + 6.6}" y1="${y - 5}" x2="${tx + 11.4}" y2="${y - 5}"
				stroke="${C.metalDark}" stroke-width="1.2"/>`;
	}
	return s;
}

/**
 * Full <svg> background for a placed part.
 *
 * @param {string} visualType  the component's visual_type
 * @param {number} w           catalogue width
 * @param {number} h           catalogue height
 * @param {object} [config]    instance config; `template_url` overrides the
 *                             vector symbol with a (desaturated) image.
 * @returns {string} an <svg> string, sized 0..w / 0..h, ready to inject.
 */
export function background(visualType, w, h, config = {}) {
	const inner = config?.template_url
		? `<image href="${config.template_url}" x="0" y="0" width="${w}" height="${h}"
				preserveAspectRatio="xMidYMid meet"
				style="filter:grayscale(1) contrast(0.9) opacity(0.85)"/>`
		: (SYMBOLS[visualType] ?? SYMBOLS.generic)(w, h);

	// overflow visible so leads/USB tabs that poke past the box still draw.
	return `<svg class="chip-symbol" viewBox="0 0 ${w} ${h}"
		width="${w}" height="${h}" xmlns="http://www.w3.org/2000/svg"
		style="overflow:visible">${inner}</svg>`;
}

/** True when a dedicated (non-generic) symbol exists for this visual_type. */
export function hasSymbol(visualType) {
	return visualType in SYMBOLS && visualType !== 'generic';
}
