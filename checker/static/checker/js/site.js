// Carverse Check — progressive enhancement only: the site works without JavaScript.
(function () {
  "use strict";

  var form = document.querySelector("[data-check-form]");
  if (!form) return;

  var input = form.querySelector("input[name='reg']");
  var button = form.querySelector("[data-check-button]");
  var progress = form.querySelector("[data-progress]");
  var steps = progress ? Array.prototype.slice.call(progress.querySelectorAll("[data-step]")) : [];
  var timers = [];

  // Keep the plate looking like a plate while typing.
  input.addEventListener("input", function () {
    var start = input.selectionStart;
    input.value = input.value.toUpperCase().replace(/[^A-Z0-9 ]/g, "");
    input.setSelectionRange(start, start);
  });

  function clearTimers() {
    timers.forEach(clearTimeout);
    timers = [];
  }

  function setStep(index) {
    steps.forEach(function (el, i) {
      el.classList.toggle("is-done", i < index);
      el.classList.toggle("is-active", i === index);
    });
  }

  function reset() {
    clearTimers();
    if (progress) progress.hidden = true;
    setStep(-1);
    button.disabled = false;
  }

  form.addEventListener("submit", function (event) {
    if (!input.value.trim()) {
      event.preventDefault();
      input.focus();
      return;
    }
    // Show the steps while the browser waits for the report page.
    // Nothing is delayed on purpose: the report opens as soon as it's ready.
    button.disabled = true;
    if (progress) {
      progress.hidden = false;
      setStep(0);
      steps.forEach(function (_, i) {
        if (i > 0) timers.push(setTimeout(function () { setStep(i); }, i * 450));
      });
    }
  });

  // Coming back with the browser's back button restores a clean form.
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) reset();
  });
})();
