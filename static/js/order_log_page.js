(function () {
  var el = document.getElementById("order-log-page");
  if (!el || !window.Dashboard) return;

  var modeEl = document.getElementById("order-filter-mode");
  var symbolWrap = document.getElementById("order-filter-symbol-wrap");
  var symbolEl = document.getElementById("order-filter-symbol");
  var rangeWrap = document.getElementById("order-filter-range-wrap");
  var fromEl = document.getElementById("order-filter-from");
  var toEl = document.getElementById("order-filter-to");
  var applyBtn = document.getElementById("order-filter-apply");
  var summaryEl = document.getElementById("order-filter-summary");
  var clearBtn = document.getElementById("order-log-clear");

  function todayKey() {
    var t = new Date();
    return (
      t.getFullYear() +
      "-" +
      String(t.getMonth() + 1).padStart(2, "0") +
      "-" +
      String(t.getDate()).padStart(2, "0")
    );
  }

  function uniqueSymbols(lines) {
    var set = {};
    lines.forEach(function (item) {
      if (item.symbol && String(item.symbol).trim()) set[String(item.symbol).trim()] = true;
    });
    return Object.keys(set).sort();
  }

  function populateSymbolOptions(lines) {
    if (!symbolEl) return;
    var prev = symbolEl.value;
    symbolEl.innerHTML = "";
    var opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = "Select symbol…";
    symbolEl.appendChild(opt0);
    uniqueSymbols(lines).forEach(function (s) {
      var o = document.createElement("option");
      o.value = s;
      o.textContent = s;
      symbolEl.appendChild(o);
    });
    if (prev && uniqueSymbols(lines).indexOf(prev) >= 0) symbolEl.value = prev;
  }

  function filterLines(lines, mode) {
    var tKey = todayKey();
    if (mode === "all") return lines.slice();

    if (mode === "today") {
      return lines.filter(function (item) {
        return item.date === tKey;
      });
    }

    if (mode === "symbol") {
      var sym = symbolEl ? symbolEl.value.trim() : "";
      if (!sym) return [];
      return lines.filter(function (item) {
        return String(item.symbol || "").trim() === sym;
      });
    }

    if (mode === "range") {
      var from = fromEl && fromEl.value ? fromEl.value : "";
      var to = toEl && toEl.value ? toEl.value : "";
      if (!from || !to) return lines.slice();
      if (from > to) {
        var tmp = from;
        from = to;
        to = tmp;
      }
      return lines.filter(function (item) {
        var d = item.date || "";
        return d >= from && d <= to;
      });
    }

    return lines.slice();
  }

  function updateFilterVisibility() {
    var mode = modeEl ? modeEl.value : "all";
    if (symbolWrap) symbolWrap.classList.toggle("hidden", mode !== "symbol");
    if (rangeWrap) rangeWrap.classList.toggle("hidden", mode !== "range");
  }

  function updateSummary(lines, filtered, mode) {
    if (!summaryEl) return;
    if (mode === "all") {
      if (lines.length === 0) {
        summaryEl.textContent = "";
        return;
      }
      summaryEl.textContent =
        "Showing all " + filtered.length + " entr" + (filtered.length === 1 ? "y" : "ies") + ".";
      return;
    }
    if (mode === "today") {
      summaryEl.textContent =
        "Today (" +
        todayKey() +
        "): " +
        filtered.length +
        " entr" +
        (filtered.length === 1 ? "y" : "ies") +
        ".";
      return;
    }
    if (mode === "symbol") {
      var sym = symbolEl && symbolEl.value ? symbolEl.value : "";
      summaryEl.textContent = sym
        ? "Symbol “" + sym + "”: " + filtered.length + " entr" + (filtered.length === 1 ? "y" : "ies") + "."
        : "Choose a symbol and click Apply.";
      return;
    }
    if (mode === "range") {
      var f = fromEl && fromEl.value ? fromEl.value : "";
      var t = toEl && toEl.value ? toEl.value : "";
      summaryEl.textContent =
        f && t
          ? "Range " + f + " → " + t + ": " + filtered.length + " entr" + (filtered.length === 1 ? "y" : "ies") + "."
          : "Pick from/to dates and click Apply.";
      return;
    }
    summaryEl.textContent = "";
  }

  function render() {
    el.innerHTML = "";
    var lines = Dashboard.readOrderLogs();
    populateSymbolOptions(lines);
    var mode = modeEl ? modeEl.value : "all";
    var filtered = filterLines(lines, mode);
    updateSummary(lines, filtered, mode);

    if (!filtered.length) {
      var row = document.createElement("div");
      row.className = "log-line log-line--muted";
      if (!lines.length) {
        row.textContent = "[—] No order log entries yet. Activity from symbol settings will appear here.";
      } else if (mode === "symbol" && symbolEl && !symbolEl.value) {
        row.textContent = "[—] Select a symbol to filter.";
      } else {
        row.textContent = "[—] No entries match this filter.";
      }
      el.appendChild(row);
      el.scrollTop = 0;
      return;
    }

    filtered.forEach(function (item) {
      var row = document.createElement("div");
      row.className = "log-line" + (item.kind === "warn" ? " log-line--warn" : "");
      var symPart = item.symbol ? " [" + item.symbol + "]" : "";
      row.textContent = "[" + item.ts + "]" + symPart + " " + item.message;
      el.appendChild(row);
    });
    el.scrollTop = el.scrollHeight;
  }

  function initRangeDefaults() {
    var t = todayKey();
    if (fromEl && !fromEl.value) fromEl.value = t;
    if (toEl && !toEl.value) toEl.value = t;
  }

  if (modeEl) {
    modeEl.addEventListener("change", function () {
      updateFilterVisibility();
      if (modeEl.value === "range") initRangeDefaults();
      render();
    });
  }
  if (applyBtn) applyBtn.addEventListener("click", render);
  if (symbolEl) symbolEl.addEventListener("change", render);
  if (fromEl) fromEl.addEventListener("change", render);
  if (toEl) toEl.addEventListener("change", render);

  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      if (!confirm("Clear all order log entries in this browser?")) return;
      Dashboard.clearOrderLogs();
      if (window.Dashboard.toast) Dashboard.toast("Order log cleared.");
      render();
    });
  }

  initRangeDefaults();
  updateFilterVisibility();
  render();
})();
