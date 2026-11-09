/* Alfurqan College — small progressive enhancements (no framework). */
(function () {
  "use strict";

  // Sidebar toggle on small screens
  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-sidebar-toggle]");
    var sb = document.querySelector(".sidebar");
    if (t && sb) { sb.classList.toggle("open"); return; }
    if (e.target.classList.contains("sidebar-backdrop") && sb) sb.classList.remove("open");
  });

  // Confirmation prompts for destructive / important actions
  document.addEventListener("submit", function (e) {
    var form = e.target;
    var msg = form.getAttribute("data-confirm") || (e.submitter && e.submitter.getAttribute("data-confirm"));
    if (msg && !window.confirm(msg)) { e.preventDefault(); return; }
    // Prevent double submission
    if (!form.hasAttribute("data-allow-resubmit")) {
      if (form.dataset.submitted === "1") { e.preventDefault(); return; }
      form.dataset.submitted = "1";
      setTimeout(function () { form.dataset.submitted = ""; }, 4000);
    }
  });

  // Client-side validation using native constraints with Bootstrap styling
  document.querySelectorAll("form.needs-validation").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!form.checkValidity()) {
        e.preventDefault(); e.stopPropagation(); form.dataset.submitted = "";
        var first = form.querySelector(":invalid"); if (first) first.focus();
      }
      form.classList.add("was-validated");
    }, true);
  });

  // Auto-dismiss toasts
  document.querySelectorAll(".toast-stack .alert").forEach(function (el, i) {
    if (el.classList.contains("alert-danger") || el.classList.contains("alert-error")) return;
    setTimeout(function () { el.style.transition = "opacity .4s"; el.style.opacity = "0"; setTimeout(function () { el.remove(); }, 400); }, 6000 + i * 600);
  });

  // Select-all checkboxes: <input data-check-all="name">
  document.querySelectorAll("[data-check-all]").forEach(function (master) {
    master.addEventListener("change", function () {
      document.querySelectorAll('input[name="' + master.dataset.checkAll + '"]').forEach(function (cb) { if (!cb.disabled) cb.checked = master.checked; });
      document.dispatchEvent(new Event("selection-changed"));
    });
  });

  // Live credit-unit counter on course registration forms
  var counter = document.querySelector("[data-unit-counter]");
  if (counter) {
    var update = function () {
      var total = parseInt(counter.dataset.base || "0", 10);
      document.querySelectorAll("input[data-units]:checked").forEach(function (cb) { total += parseInt(cb.dataset.units, 10) || 0; });
      counter.textContent = total;
      var max = parseInt(counter.dataset.max || "0", 10);
      counter.classList.toggle("text-danger", max > 0 && total > max);
    };
    document.addEventListener("change", function (e) { if (e.target.matches("input[data-units]")) update(); });
    document.addEventListener("selection-changed", update);
    update();
  }

  // Live totals on score entry grids
  document.querySelectorAll("tr[data-score-row]").forEach(function (row) {
    var ca = row.querySelector("[data-ca]"), ex = row.querySelector("[data-exam]"), out = row.querySelector("[data-total]");
    var calc = function () {
      var a = parseFloat(ca.value), b = parseFloat(ex.value);
      out.textContent = (isNaN(a) || isNaN(b)) ? "—" : (a + b).toFixed(2).replace(/\.00$/, "");
      [ca, ex].forEach(function (inp) {
        var v = parseFloat(inp.value), m = parseFloat(inp.max);
        inp.classList.toggle("is-invalid", !isNaN(v) && (v < 0 || v > m));
      });
    };
    [ca, ex].forEach(function (i) { i.addEventListener("input", calc); });
    calc();
  });

  // Reveal-on-scroll for website sections
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); } });
    }, { threshold: 0.12 });
    document.querySelectorAll(".reveal").forEach(function (el) { io.observe(el); });
  } else {
    document.querySelectorAll(".reveal").forEach(function (el) { el.classList.add("in"); });
  }

  // Show chosen file name for custom upload zones
  document.querySelectorAll("input[type=file][data-filename-target]").forEach(function (inp) {
    inp.addEventListener("change", function () {
      var t = document.getElementById(inp.dataset.filenameTarget);
      if (t) t.textContent = inp.files.length ? inp.files[0].name : "";
    });
  });
})();
