// code-visuals kit: rough.js helpers that draw around laid-out text (freeform pages), plus the checker every page gets.
// render.py inlines rough.js, this file, window.__LABELS and the canvas size into the page, then reads #__check
// (via Chrome --dump-dom), takes the screenshot and crops it to the content box the checker reports.
(function () {
  const C = {
    ink: '#2b2b2b', blue: '#2a62a8', green: '#3c8a5a', orange: '#c0621b', red: '#b8423a', purple: '#6a4fa0',
    lblue: '#dbe8f7', lgreen: '#dff0e3', lorange: '#fbe3cf', lred: '#f8dcd8', lpurple: '#e7def5', yellow: '#fff1a8',
  };
  const col = c => C[c] || c;
  let svg, rc;

  function rectOf(sel) {
    const els = typeof sel === 'string' ? [...document.querySelectorAll(sel)] : [sel];
    if (!els.length) throw new Error('kit: nothing matches ' + sel);
    const rs = els.map(e => e.getBoundingClientRect());
    const x = Math.min(...rs.map(r => r.left)), y = Math.min(...rs.map(r => r.top));
    return { x, y, w: Math.max(...rs.map(r => r.right)) - x, h: Math.max(...rs.map(r => r.bottom)) - y };
  }
  const add = n => (svg.appendChild(n), n);
  const center = r => [r.x + r.w / 2, r.y + r.h / 2];

  // Point where the ray from the rect's center toward (tx, ty) leaves the rect grown by pad.
  function exit(r, tx, ty, pad) {
    const [cx, cy] = center(r), dx = tx - cx, dy = ty - cy;
    const sx = dx ? (r.w / 2 + pad) / Math.abs(dx) : Infinity, sy = dy ? (r.h / 2 + pad) / Math.abs(dy) : Infinity;
    const s = Math.min(sx, sy);
    return [cx + dx * s, cy + dy * s];
  }

  window.kit = {
    C, get rc() { return rc; },
    // Rounded hand-drawn frame around the element(s); fill is solid so text on top stays clean.
    box(sel, o = {}) {
      const r = rectOf(sel), p = o.pad ?? 22;
      return add(rc.rectangle(r.x - p, r.y - p, r.w + 2 * p, r.h + 2 * p, {
        stroke: col(o.color || 'ink'), strokeWidth: o.width ?? 3.5, roughness: o.roughness ?? 1.8,
        fill: o.fill ? col(o.fill) : undefined, fillStyle: 'solid',
      }));
    },
    banner(sel, o = {}) { return this.box(sel, { fill: 'yellow', pad: 26, ...o }); },
    underline(sel, o = {}) {
      const r = rectOf(sel);
      return add(rc.line(r.x, r.y + r.h + 8, r.x + r.w, r.y + r.h + 8, { stroke: col(o.color || 'ink'), strokeWidth: o.width ?? 4, roughness: 2 }));
    },
    // Arrow from one element to another, starting and ending outside both (pad px), so it never crosses their text.
    arrow(from, to, o = {}) {
      const a = rectOf(from), b = rectOf(to), pad = o.pad ?? 30;
      const [x1, y1] = exit(a, ...center(b), pad), [x2, y2] = exit(b, ...center(a), pad);
      const s = { stroke: col(o.color || 'ink'), strokeWidth: o.width ?? 4, roughness: 1.2 };
      const ang = Math.atan2(y2 - y1, x2 - x1), L = 22;
      add(rc.line(x1, y1, x2, y2, s));
      add(rc.line(x2, y2, x2 - L * Math.cos(ang - 0.45), y2 - L * Math.sin(ang - 0.45), s));
      add(rc.line(x2, y2, x2 - L * Math.cos(ang + 0.45), y2 - L * Math.sin(ang + 0.45), s));
    },
    rect: sel => rectOf(sel),
    square(x, y, d, o = {}) { return add(rc.rectangle(x, y, d, d, { stroke: col(o.color || 'ink'), fill: o.fill ? col(o.fill) : undefined, fillStyle: 'solid', strokeWidth: o.width ?? 2.5, roughness: 1.3 })); },
    circle(x, y, d, o = {}) { return add(rc.circle(x, y, d, { stroke: col(o.color || 'ink'), fill: o.fill ? col(o.fill) : undefined, fillStyle: 'solid', strokeWidth: o.width ?? 2.5 })); },
    line(x1, y1, x2, y2, o = {}) { return add(rc.line(x1, y1, x2, y2, { stroke: col(o.color || 'ink'), strokeWidth: o.width ?? 3, roughness: o.roughness ?? 1.5 })); },
  };

  // Every text on the picture must be one of the labels (decorative numbering and arrows aside),
  // stay inside the canvas, not overlap other text, and not be crossed by a drawn stroke.
  const DECOR = /^[\s①-⑳❶-❿0-9.、,，:：→←↑↓⇒⇢·•()（）+\-–—=×✓✗?？!！]+|[\s①-⑳❶-❿0-9.、,，:：→←↑↓⇒⇢·•()（）+\-–—=×✓✗?？!！]+$/g;
  function check(W, H) {
    const labels = new Set((window.__LABELS || []).map(s => s.replace(/\s+/g, ' ').trim()));
    const problems = [], warnings = [], texts = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const groups = new Map();
    while (walker.nextNode()) {
      const n = walker.currentNode, p = n.parentElement;
      if (!p || p.closest('script,style,#__check') || !n.textContent.trim()) continue;
      if (!groups.has(p)) groups.set(p, []);
      groups.get(p).push(n);
    }
    const used = new Set();
    for (const [el, nodes] of groups) {
      const raw = nodes.map(n => n.textContent).join('').replace(/\s+/g, ' ').trim();
      const core = raw.replace(DECOR, '').trim();
      const numbering = /^(0?[1-9]|1[0-9]|20)$/.test(raw.replace(/[\s.、①-⑳❶-❿()（）]/g, '')) || /^vs\.?$/i.test(raw);
      if (!labels.has(raw) && !labels.has(core) && !(core === '' && numbering) && !/^[\s→←↑↓⇒⇢·•+\-–—=×✓✗]+$/.test(raw))
        problems.push(`text not in labels: "${raw}"`);
      used.add(core); used.add(raw);
      const range = document.createRange(); range.setStartBefore(nodes[0]); range.setEndAfter(nodes[nodes.length - 1]);
      const r = range.getBoundingClientRect();
      if (r.left < 0 || r.top < 0 || r.right > W + 0.5 || r.bottom > H + 0.5) problems.push(`text outside the canvas: "${raw}"`);
      // Rendered size, not the declared one: engines scale whole SVGs. One character's box height ≈ 1.2-1.4 × font size.
      const one = document.createRange(), first = nodes[0], k = first.textContent.search(/\S/);
      one.setStart(first, k); one.setEnd(first, k + 1);
      const fs = Math.round(Math.min(parseFloat(getComputedStyle(el).fontSize) * 1.0, one.getBoundingClientRect().height / 1.25) * 10) / 10;
      texts.push({ raw, r, fs });
    }
    for (const l of labels) if (!used.has(l)) warnings.push(`label not drawn: "${l}"`);
    const hit = (a, b, m = 2) => a.left + m < b.right && b.left + m < a.right && a.top + m < b.bottom && b.top + m < a.bottom;
    for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++)
      if (hit(texts[i].r, texts[j].r)) problems.push(`text overlaps text: "${texts[i].raw}" / "${texts[j].raw}"`);
    // Sample each hand-drawn stroke (freeform #ink layer only; engines such as AntV lay out their own shapes and
    // fill cards with hatching under the words). A point inside a text box (shrunk 3px) means a line runs through it.
    for (const g of document.querySelectorAll('#ink path, #ink line, #ink polyline')) {
      const st = g.getAttribute('stroke'); if (!st || st === 'none' || g.closest('#__check')) continue;
      let len = 0; try { len = g.getTotalLength(); } catch (e) { continue; }
      const m = g.getScreenCTM(); if (!m) continue;
      for (const t of texts) {
        const r = t.r;
        for (let s = 0; s <= len; s += 4) {
          const q = g.getPointAtLength(s), x = m.a * q.x + m.c * q.y + m.e, y = m.b * q.x + m.d * q.y + m.f;
          if (x > r.left + 3 && x < r.right - 3 && y > r.top + 3 && y < r.bottom - 3) { problems.push(`a drawn line crosses text: "${t.raw}"`); break; }
        }
      }
    }
    // Content box for cropping: every text plus every visible shape smaller than the canvas (skips page backgrounds).
    let x0 = W, y0 = H, x1 = 0, y1 = 0;
    const grow = r => { if (r.width < 1 || r.height < 1) return; x0 = Math.min(x0, r.left); y0 = Math.min(y0, r.top); x1 = Math.max(x1, r.right); y1 = Math.max(y1, r.bottom); };
    texts.forEach(t => grow(t.r));
    for (const g of document.querySelectorAll('svg path, svg rect, svg circle, svg ellipse, svg line, svg polyline, svg polygon, svg image, img')) {
      const r = g.getBoundingClientRect();
      if (r.width < W * 0.98 || r.height < H * 0.98) grow(r);
    }
    // The picture is shown at page width (about 360-560px on a phone), so what matters is text size relative to the
    // cropped content width: below 2% the words shrink under ~9px on a phone. Pick a narrower layout instead.
    const cw = Math.max(1, Math.min(W, x1) - Math.max(0, x0));
    for (const t of texts) {
      const ratio = t.fs / cw;
      if (ratio < 0.02) problems.push(`text too small for the picture width (${t.fs}px in ${Math.round(cw)}px; use a narrower layout or fewer items): "${t.raw}"`);
      else if (ratio < 0.026) warnings.push(`small text (${t.fs}px in ${Math.round(cw)}px wide content): "${t.raw}"`);
    }
    const box = x1 > x0 ? { x: Math.max(0, x0), y: Math.max(0, y0), w: Math.min(W, x1) - Math.max(0, x0), h: Math.min(H, y1) - Math.max(0, y0) } : null;
    return { problems: [...new Set(problems)], warnings: [...new Set(warnings)], box };
  }

  addEventListener('load', async () => {
    const W = window.__W, H = window.__H, out = document.createElement('pre');
    out.id = '__check'; out.style.display = 'none';
    let result;
    try {
      if (window.__ready) await window.__ready;  // engines that render asynchronously (AntV) set this
      try { await document.fonts.ready; } catch (e) { /* fonts optional */ }
      if (typeof window.paint === 'function') {
        svg = document.getElementById('ink');
        if (!svg) { svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.id = 'ink'; document.body.prepend(svg); }
        svg.setAttribute('width', W); svg.setAttribute('height', H);
        svg.style.cssText += ';position:absolute;left:0;top:0;z-index:0;pointer-events:none';
        rc = rough.svg(svg);
        window.paint(window.kit);
      }
      result = check(W, H);
    } catch (e) {
      result = { problems: ['page script failed: ' + e.message], warnings: [] };
    }
    out.textContent = JSON.stringify(result);
    document.body.appendChild(out);
  });
})();
