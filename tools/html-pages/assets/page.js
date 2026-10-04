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

  function labelText(input) {
    return Array.from(input.labels || []).map(function (label) { return label.textContent.trim(); }).join(' ');
  }

  // Predict and reveal: choose, lock in, then reveal as a separate action, or reset.
  function enhancePredict(root) {
    var questions = Array.from(root.querySelectorAll('[data-predict-question]'));
    var lock = root.querySelector('button[data-predict-lock]');
    var reveal = root.querySelector('button[data-predict-reveal]');
    var reset = root.querySelector('button[data-predict-reset]');
    var status = root.querySelector('[data-predict-status]');
    if (!questions.length || !lock || !reveal || !reset || !status) return;
    var parts = questions.map(function (question) {
      return {
        radios: Array.from(question.querySelectorAll('input[type="radio"]')),
        answer: question.querySelector('[data-predict-answer]'),
        result: question.querySelector('[data-predict-result]'),
      };
    });
    if (parts.some(function (part) {
      return part.radios.length < 2 || !part.answer || !part.result ||
        part.radios.filter(function (radio) { return radio.hasAttribute('data-correct'); }).length !== 1;
    })) return;
    var locked = false;
    var revealed = false;
    var noun = questions.length === 1 ? 'an answer' : 'an answer for every question';

    function chosen(part) {
      return part.radios.filter(function (radio) { return radio.checked; })[0] || null;
    }
    function render() {
      var complete = parts.every(chosen);
      parts.forEach(function (part) {
        part.radios.forEach(function (radio) { radio.disabled = locked; });
        part.answer.hidden = !revealed;
        if (!revealed) part.result.textContent = '';
        else {
          var correct = part.radios.filter(function (radio) { return radio.hasAttribute('data-correct'); })[0];
          part.result.textContent = chosen(part) === correct ? 'Correct.' : 'Not quite. The answer is ' + labelText(correct) + '.';
        }
      });
      lock.disabled = locked || !complete;
      reveal.disabled = !locked || revealed;
      reset.disabled = false;
      if (revealed) {
        var score = parts.filter(function (part) { return chosen(part) && chosen(part).hasAttribute('data-correct'); }).length;
        status.textContent = 'Revealed: ' + score + ' of ' + parts.length + ' correct.';
      } else if (locked) status.textContent = 'Locked in. Reveal when everyone has locked in.';
      else status.textContent = complete ? 'Ready to lock in.' : 'Choose ' + noun + ', then lock in.';
    }

    root.addEventListener('change', function (event) {
      if (event.target instanceof HTMLInputElement && event.target.type === 'radio') render();
    });
    lock.addEventListener('click', function () {
      if (!parts.every(chosen)) return;
      var hadFocus = document.activeElement === lock;
      locked = true;
      render();
      if (hadFocus) reveal.focus();
    });
    reveal.addEventListener('click', function () {
      if (!locked) return;
      var hadFocus = document.activeElement === reveal;
      revealed = true;
      render();
      if (hadFocus) reset.focus();
    });
    reset.addEventListener('click', function () {
      locked = false;
      revealed = false;
      parts.forEach(function (part) { part.radios.forEach(function (radio) { radio.checked = false; }); });
      render();
      parts[0].radios[0].focus();
    });
    render();
  }

  // Probability bars: authored labels and values, an SVG bar per row once enhanced.
  function enhanceProbChart(chart) {
    var svgNS = 'http://www.w3.org/2000/svg';
    function renderRow(row) {
      var label = row.querySelector('[data-prob-label]');
      var value = row.querySelector('[data-prob-value]');
      if (!label || !value) return;
      var raw = row.getAttribute('data-value');
      var number = raw === null || raw.trim() === '' ? NaN : Number(raw);
      var valid = Number.isFinite(number) && number >= 0 && number <= 1;
      var highlighted = row.hasAttribute('data-highlight');
      var svg = row.querySelector('svg.prob-bar');
      var flag = label.querySelector('[data-prob-flag]');
      if (highlighted && !flag) {
        flag = document.createElement('span');
        flag.className = 'visually-hidden';
        flag.setAttribute('data-prob-flag', '');
        flag.textContent = ' (highlighted)';
        label.appendChild(flag);
      } else if (!highlighted && flag) flag.remove();
      if (!valid) {
        if (svg) svg.remove();
        value.textContent = 'n/a';
        return;
      }
      if (!svg) {
        svg = document.createElementNS(svgNS, 'svg');
        svg.setAttribute('class', 'prob-bar');
        svg.setAttribute('aria-hidden', 'true');
        svg.setAttribute('focusable', 'false');
        ['track', 'bar'].forEach(function () {
          var rect = document.createElementNS(svgNS, 'rect');
          rect.setAttribute('height', '100%');
          svg.appendChild(rect);
        });
        row.insertBefore(svg, value);
      }
      var rects = svg.querySelectorAll('rect');
      rects[0].setAttribute('class', 'f-faint');
      rects[0].setAttribute('width', '100%');
      rects[1].setAttribute('class', highlighted ? 'f-accent' : 'f-muted');
      rects[1].setAttribute('width', number * 100 + '%');
      value.textContent = (number * 100).toFixed(1) + '%';
    }
    chart.querySelectorAll('[data-prob-row]').forEach(renderRow);
    new MutationObserver(function (records) {
      var rows = [];
      records.forEach(function (record) {
        if (record.target.matches('[data-prob-row]') && rows.indexOf(record.target) < 0) rows.push(record.target);
      });
      rows.forEach(renderRow);
    }).observe(chart, { subtree: true, attributes: true, attributeFilter: ['data-value', 'data-highlight'] });
  }

  // Labelled slider whose readout comes from window.CursusFormulas[name](value, root).
  function enhanceFormula(root) {
    var input = root.querySelector('input[type="range"][data-formula-input]');
    var output = root.querySelector('output[data-formula-output]');
    var reset = root.querySelector('button[data-formula-reset]');
    var formulas = window.CursusFormulas;
    var formula = formulas && Object.prototype.hasOwnProperty.call(formulas, root.getAttribute('data-formula'))
      ? formulas[root.getAttribute('data-formula')] : null;
    if (!input || !output || !reset || typeof formula !== 'function') return;
    function update() {
      var text = String(formula(Number(input.value), root)).trim();
      output.textContent = text;
      input.setAttribute('aria-valuetext', text);
    }
    input.addEventListener('input', update);
    reset.addEventListener('click', function () { input.value = input.defaultValue; update(); });
    update();
    input.disabled = false;
    reset.disabled = false;
  }

  // Step-through controller; arrow keys act only on the focused stage itself.
  function enhanceStepper(root) {
    var stage = root.querySelector('[data-step-stage]');
    var controls = root.querySelector('[data-step-controls]');
    if (!stage || !controls) return;
    var steps = Array.from(stage.querySelectorAll('[data-step]'));
    var previous = controls.querySelector('button[data-step-prev]');
    var next = controls.querySelector('button[data-step-next]');
    var reset = controls.querySelector('button[data-step-reset]');
    var status = controls.querySelector('[data-step-status]');
    if (!steps.length || !previous || !next || !reset || !status) return;
    var current = 0;

    function render() {
      var focused = document.activeElement;
      steps.forEach(function (step, index) { step.hidden = index !== current; });
      previous.disabled = current === 0;
      next.disabled = current === steps.length - 1;
      status.textContent = 'Step ' + (current + 1) + ' of ' + steps.length;
      root.setAttribute('data-step-current', String(current));
      if ((focused === previous && previous.disabled) || (focused === next && next.disabled) ||
          steps.some(function (step) { return step.hidden && step.contains(focused); })) stage.focus();
    }
    function go(index) {
      index = Math.max(0, Math.min(steps.length - 1, index));
      if (index === current) return;
      current = index;
      render();
      root.dispatchEvent(new CustomEvent('cursus:step', { bubbles: true, detail: { index: current } }));
    }

    previous.addEventListener('click', function () { go(current - 1); });
    next.addEventListener('click', function () { go(current + 1); });
    reset.addEventListener('click', function () { go(0); });
    stage.addEventListener('keydown', function (event) {
      if (event.target !== stage || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      var index;
      if (event.key === 'ArrowLeft') index = current - 1;
      else if (event.key === 'ArrowRight') index = current + 1;
      else if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = steps.length - 1;
      else return;
      event.preventDefault();
      go(index);
    });
    controls.hidden = false;
    render();
  }

  function init() {
    enhanceDisclosurePrint();
    document.querySelectorAll('[data-deck]').forEach(enhanceDeck);
    document.querySelectorAll('[data-lab]').forEach(enhanceLab);
    document.querySelectorAll('[data-predict]').forEach(enhancePredict);
    document.querySelectorAll('[data-prob-chart]').forEach(enhanceProbChart);
    document.querySelectorAll('[data-formula]').forEach(enhanceFormula);
    document.querySelectorAll('[data-stepper]').forEach(enhanceStepper);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
