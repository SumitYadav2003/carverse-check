// Carverse Check — progressive enhancement only: the site works without JavaScript.

// ---------- site header: menu button on small screens ----------
(function () {
  "use strict";
  var header = document.querySelector("[data-header]");
  var button = document.querySelector("[data-menu-button]");
  if (!header || !button) return;

  function setOpen(open) {
    header.classList.toggle("is-open", open);
    button.setAttribute("aria-expanded", open ? "true" : "false");
  }
  button.addEventListener("click", function () {
    setOpen(!header.classList.contains("is-open"));
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && header.classList.contains("is-open")) {
      setOpen(false);
      button.focus();
    }
  });
  // close when a link inside it is followed (same-page anchors)
  header.addEventListener("click", function (event) {
    if (event.target.closest("#site-nav a")) setOpen(false);
  });
})();

// ---------- report: print, copy link, "on this page" highlighting ----------
(function () {
  "use strict";
  var printButton = document.querySelector("[data-print]");
  if (printButton) printButton.addEventListener("click", function () { window.print(); });

  var copyButton = document.querySelector("[data-copy-link]");
  if (copyButton) {
    var label = copyButton.querySelector("[data-copy-label]");
    var original = label.textContent;
    copyButton.addEventListener("click", function () {
      var url = window.location.href.split("#")[0];
      function done(text) {
        label.textContent = text;
        copyButton.classList.add("is-done");
        setTimeout(function () {
          label.textContent = original;
          copyButton.classList.remove("is-done");
        }, 2400);
      }
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(url).then(function () { done("Link copied"); },
                                                function () { done("Couldn't copy: use the address bar"); });
      } else {
        done("Copy the address from your browser's address bar");
      }
    });
    copyButton.setAttribute("aria-live", "polite");
  }

  var links = Array.prototype.slice.call(document.querySelectorAll("[data-toc]"));
  if (!links.length || !("IntersectionObserver" in window)) return;
  var byId = {};
  links.forEach(function (a) { byId[a.getAttribute("href").slice(1)] = a; });
  var visible = {};
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) { visible[e.target.id] = e.isIntersecting; });
    // highlight the first section (in page order) that is on screen
    var current = null;
    links.forEach(function (a) {
      var id = a.getAttribute("href").slice(1);
      if (!current && visible[id]) current = id;
    });
    links.forEach(function (a) { a.classList.toggle("is-current", a === byId[current]); });
  }, { rootMargin: "-80px 0px -45% 0px" });
  Object.keys(byId).forEach(function (id) {
    var section = document.getElementById(id);
    if (section) observer.observe(section);
  });
})();

// ---------- home: the number plate form ----------
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
