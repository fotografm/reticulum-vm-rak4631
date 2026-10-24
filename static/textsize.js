/* textsize.js — per-page size control for the ct168 web pages.
 *
 * Brave/Chrome keep ONE zoom level per host and ignore the port, so zooming
 * :8085 also zooms :80, :8090 ... on the same IP. This adds a small
 * "A− 100% A+" control (bottom right) and remembers the size in localStorage,
 * which IS separate per port. Leave the browser's own zoom at 100 %.
 *
 * Default: CSS zoom on <html>. A page can set window.PAGEZOOM_APPLY = fn(f)
 * BEFORE loading this script to scale itself (the terminal changes xterm's
 * font size instead, because zooming the page breaks xterm's measurements).
 *
 * Same file is served by the landing / services / terminal servers
 * (/static/textsize.js), inlined into rns-map's index.html and muweb pages
 * by install-nomadnet.sh.
 */
(function () {
    'use strict';
    var KEY = 'pagezoom';
    var STEPS = [0.5, 0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3];
    var f = 1;

    function load() {
        try {
            var v = parseFloat(localStorage.getItem(KEY));
            if (v >= STEPS[0] && v <= STEPS[STEPS.length - 1]) f = v;
        } catch (e) {}
    }
    function save() {
        try {
            if (f === 1) localStorage.removeItem(KEY);
            else localStorage.setItem(KEY, String(f));
        } catch (e) {}
    }

    var label;
    function apply() {
        if (typeof window.PAGEZOOM_APPLY === 'function') window.PAGEZOOM_APPLY(f);
        else document.documentElement.style.zoom = f === 1 ? '' : String(f);
        if (label) label.textContent = Math.round(f * 100) + '%';
        // let pages that size themselves from the window (rns-map) redraw
        window.dispatchEvent(new Event('resize'));
    }
    function step(dir) {
        var i = STEPS.indexOf(f);
        if (i < 0) i = STEPS.indexOf(1);
        i = Math.max(0, Math.min(STEPS.length - 1, i + dir));
        f = STEPS[i];
        save();
        apply();
    }

    function button(text, title, onclick) {
        var b = document.createElement('button');
        b.type = 'button';
        b.textContent = text;
        b.title = title;
        b.onclick = onclick;
        b.style.cssText = 'all:unset;cursor:pointer;padding:2px 7px;color:#9fd;' +
            'font:12px/1.4 "DejaVu Sans Mono",Consolas,monospace;';
        return b;
    }

    function widget() {
        var w = document.createElement('div');
        w.id = 'pagezoom';
        // zoom:1/f would fight the page zoom; it is fine if the control scales too
        w.style.cssText = 'position:fixed;right:6px;bottom:6px;z-index:2147483647;' +
            'display:flex;align-items:center;background:rgba(0,0,0,.65);' +
            'border:1px solid #2a4a4a;border-radius:4px;opacity:.55;user-select:none;';
        w.onmouseenter = function () { w.style.opacity = '1'; };
        w.onmouseleave = function () { w.style.opacity = '.55'; };
        w.appendChild(button('A−', 'Smaller', function () { step(-1); }));
        label = button('100%', 'Reset to 100 %', function () { f = 1; save(); apply(); });
        label.style.color = '#ccc';
        w.appendChild(label);
        w.appendChild(button('A+', 'Larger', function () { step(1); }));
        document.body.appendChild(w);
    }

    load();
    function start() { widget(); apply(); }
    if (document.body) start();
    else document.addEventListener('DOMContentLoaded', start);
})();
