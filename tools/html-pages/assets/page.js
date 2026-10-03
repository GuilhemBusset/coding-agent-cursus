/* Classic script; each enhancement is optional and scoped to its own root. */
(function () {
  'use strict';

  function enhanceDisclosurePrint() {
    var snapshot = null;
    function openForPrint() {
      if (snapshot) return;
      snapshot = Array.from(document.querySelectorAll('details')).map(function (details) {
        return { element: details, open: details.open, name: details.getAttribute('name') };
      });
      // Named disclosure groups allow only one open member; suspend that grouping.
      snapshot.forEach(function (item) { item.element.removeAttribute('name'); });
      snapshot.forEach(function (item) { item.element.open = true; });
    }
    function restore() {
      if (!snapshot) return;
      snapshot.forEach(function (item) { item.element.open = false; });
      snapshot.forEach(function (item) {
        if (item.name !== null) item.element.setAttribute('name', item.name);
        item.element.open = item.open;
      });
      snapshot = null;
    }
    var print = window.matchMedia('print');
    window.addEventListener('beforeprint', openForPrint);
    window.addEventListener('afterprint', restore);
    print.addEventListener('change', function () {
      if (print.matches) openForPrint();
      else restore();
    });
    if (print.matches) openForPrint();
  }

  function enhanceDeck(deck) {
    var slides = Array.from(deck.querySelectorAll('[data-slide]'));
    var nav = deck.querySelector('[data-deck-nav]');
    if (!slides.length || !nav) return;
    var previous = nav.querySelector('[data-prev]');
    var next = nav.querySelector('[data-next]');
    var status = nav.querySelector('[data-slide-status]');
    if (!previous || !next || !status) return;
    var wide = window.matchMedia('(min-width: 800px) and (min-height: 600px)');
    var print = window.matchMedia('print');
    var printing = false;
    var current = 0;

    function hashIndex() {
      var id;
      try { id = decodeURIComponent(window.location.hash.slice(1)); }
      catch (_) { return -1; }
      if (!id) return 0;
      var target = document.getElementById(id);
      return target ? slides.indexOf(target.closest('[data-slide]')) : -1;
    }

    function render() {
      var paged = wide.matches && !print.matches && !printing;
      var focused = document.activeElement;
      var hidingFocus = paged && slides.some(function (slide, index) {
        return index !== current && slide.contains(focused);
      });
      var hidingNavFocus = !paged && nav.contains(focused);
      document.documentElement.toggleAttribute('data-deck-paged', paged);
      slides.forEach(function (slide, index) {
        var inactive = paged && index !== current;
        slide.hidden = inactive;
        slide.toggleAttribute('inert', inactive);
        slide.tabIndex = paged && !inactive ? 0 : -1;
      });
      nav.hidden = !paged;
      previous.disabled = current === 0;
      next.disabled = current === slides.length - 1;
      status.textContent = 'Slide ' + (current + 1) + ' of ' + slides.length;
      if (hidingFocus || hidingNavFocus) slides[current].focus({ preventScroll: true });
      else if ((focused === previous && previous.disabled) || (focused === next && next.disabled)) {
        var fallback = focused === previous ? next : previous;
        (fallback.disabled ? slides[current] : fallback).focus({ preventScroll: true });
      }
    }

    function go(index) {
      index = Math.max(0, Math.min(slides.length - 1, index));
      if (index === current) return;
      current = index;
      // pushState preserves Back/Forward without scrolling the page to the hash.
      try { window.history.pushState(null, '', '#' + encodeURIComponent(slides[current].id)); }
      catch (_) { window.location.hash = slides[current].id; }
      render();
    }

    function readLocation() {
      var index = hashIndex();
      if (index >= 0) current = index;
      render();
      if (index >= 0 && window.location.hash) {
        var target = document.getElementById(decodeURIComponent(window.location.hash.slice(1)));
        if (target && target !== slides[current]) target.scrollIntoView({ block: 'nearest' });
      }
    }

    previous.addEventListener('click', function () { go(current - 1); });
    next.addEventListener('click', function () { go(current + 1); });
    document.addEventListener('keydown', function (event) {
      if (nav.hidden || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      var target = event.target;
      if (target instanceof Element && (target.isContentEditable || target.closest('input, textarea, select, button, a, summary, pre, [role="region"], [tabindex]:not([data-slide]):not([data-deck]), [contenteditable], [role="button"], [role="slider"], [role="radio"], [role="tab"], [role="textbox"], [role="combobox"], [role="listbox"], [role="spinbutton"], audio, video'))) return;
      var index;
      if (event.key === 'ArrowLeft' || event.key === 'PageUp') index = current - 1;
      else if (event.key === 'ArrowRight' || event.key === 'PageDown' || event.key === ' ') index = current + 1;
      else if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = slides.length - 1;
      else return;
      event.preventDefault();
      go(index);
    });
    window.addEventListener('hashchange', readLocation);
    window.addEventListener('popstate', readLocation);
    wide.addEventListener('change', render);
    print.addEventListener('change', render);
    window.addEventListener('beforeprint', function () { printing = true; render(); });
    window.addEventListener('afterprint', function () { printing = false; render(); });
    deck.setAttribute('data-enhanced', '');
    readLocation();
  }

  function enhanceLab(lab) {
    var slider = lab.querySelector('[data-budget]');
    var output = lab.querySelector('[data-budget-output]');
    var used = lab.querySelector('[data-budget-used]');
    var remaining = lab.querySelector('[data-budget-remaining]');
    var meter = lab.querySelector('[data-budget-meter]');
    var reset = lab.querySelector('[data-reset]');
    if (!slider || !output || !used || !remaining || !meter || !reset) return;
    var total = Number(lab.getAttribute('data-budget-total'));
    var fixed = Number(lab.getAttribute('data-budget-fixed'));
    if (!Number.isFinite(total) || !Number.isFinite(fixed) || total <= 0 || fixed < 0 || Number(slider.max) + fixed > total) return;
    function update() {
      var context = Number(slider.value);
      var consumed = fixed + context;
      output.textContent = String(context);
      used.textContent = String(consumed);
      remaining.textContent = String(total - consumed);
      meter.value = consumed;
      meter.textContent = consumed + ' of ' + total + ' tokens used';
      slider.setAttribute('aria-valuetext', context + ' context tokens; ' + (total - consumed) + ' tokens remaining');
    }
    slider.addEventListener('input', update);
    reset.addEventListener('click', function () { slider.value = slider.defaultValue; update(); });
    update();
    slider.disabled = false;
    reset.disabled = false;
  }

  function init() {
    enhanceDisclosurePrint();
    document.querySelectorAll('[data-deck]').forEach(enhanceDeck);
    document.querySelectorAll('[data-lab]').forEach(enhanceLab);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
