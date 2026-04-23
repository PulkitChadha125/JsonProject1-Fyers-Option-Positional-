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
  var pnlEl = document.getElementById("order-filter-pnl");
  var clearBtn = document.getElementById("order-log-clear");
  var exportBtn = document.getElementById("order-log-export-csv");

  var detailModal = document.getElementById("order-detail-modal");
  var detailBackdrop = document.getElementById("order-detail-backdrop");
  var detailClose = document.getElementById("order-detail-close");
  var detailCloseBtn = document.getElementById("order-detail-close-btn");
  var detailBody = document.getElementById("order-detail-body");
  var detailTitle = document.getElementById("order-detail-title");

  var serverLines = [];

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

  function safeNumber(v) {
    var n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }

  function normalizeLine(item) {
    if (!item || typeof item !== "object") return null;
    return {
      ts: item.ts != null ? String(item.ts) : "00:00:00",
      date: item.date != null ? String(item.date) : "",
      iso: item.iso != null ? String(item.iso) : "",
      message: item.message != null ? String(item.message) : "",
      kind: item.kind != null ? String(item.kind) : "info",
      symbol: item.symbol != null ? String(item.symbol).trim() : "",
      pnl: item.pnl == null ? null : safeNumber(item.pnl),
      details: item.details && typeof item.details === "object" ? item.details : {},
    };
  }

  function csvEscape(v) {
    var s = v == null ? "" : String(v);
    if (s.indexOf('"') >= 0) s = s.replace(/"/g, '""');
    if (/[",\n]/.test(s)) s = '"' + s + '"';
    return s;
  }

  function downloadCsv(filename, rows) {
    var csv = rows.join("\n");
    var blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
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

  function getMergedLines() {
    var lines = Dashboard.readOrderLogs()
      .concat(serverLines)
      .map(normalizeLine)
      .filter(Boolean);
    var seen = {};
    lines = lines.filter(function (item) {
      var key =
        String(item.iso || "") +
        "|" +
        String(item.symbol || "") +
        "|" +
        String(item.kind || "") +
        "|" +
        String(item.message || "") +
        "|" +
        String(item.pnl == null ? "" : item.pnl);
      if (seen[key]) return false;
      seen[key] = true;
      return true;
    });
    lines.sort(function (a, b) {
      var ia = String(a.iso || "");
      var ib = String(b.iso || "");
      if (ia < ib) return -1;
      if (ia > ib) return 1;
      return 0;
    });
    return lines;
  }

  function getActiveFilteredLines(lines) {
    var mode = modeEl ? modeEl.value : "all";
    return filterLines(lines, mode);
  }

  function updateFilterVisibility() {
    var mode = modeEl ? modeEl.value : "all";
    if (symbolWrap) symbolWrap.classList.toggle("hidden", mode !== "symbol");
    if (rangeWrap) rangeWrap.classList.toggle("hidden", mode !== "range");
  }

  function updateSummary(lines, filtered, mode) {
    if (!summaryEl) return;
    if (mode === "all") {
      summaryEl.textContent = lines.length === 0 ? "" : "Showing all " + filtered.length + " entries.";
      return;
    }
    if (mode === "today") {
      summaryEl.textContent = "Today (" + todayKey() + "): " + filtered.length + " entries.";
      return;
    }
    if (mode === "symbol") {
      var sym = symbolEl && symbolEl.value ? symbolEl.value : "";
      summaryEl.textContent = sym ? "Symbol '" + sym + "': " + filtered.length + " entries." : "Choose a symbol and click Apply.";
      return;
    }
    if (mode === "range") {
      var f = fromEl && fromEl.value ? fromEl.value : "";
      var t = toEl && toEl.value ? toEl.value : "";
      summaryEl.textContent = f && t ? "Range " + f + " -> " + t + ": " + filtered.length + " entries." : "Pick from/to dates and click Apply.";
      return;
    }
    summaryEl.textContent = "";
  }

  function updateTotalPnl(filtered) {
    if (!pnlEl) return;
    var total = filtered.reduce(function (sum, item) {
      if (item.pnl == null) return sum;
      var d = item.details || {};
      if (String(d.action || "").toUpperCase() !== "SELL") return sum;
      return sum + safeNumber(item.pnl);
    }, 0);
    pnlEl.textContent = "Total P&L (selected): " + total.toFixed(2);
    pnlEl.classList.toggle("is-negative", total < 0);
    pnlEl.classList.toggle("is-positive", total > 0);
  }

  function hasDetails(item) {
    return !!(item && item.details && typeof item.details === "object" && Object.keys(item.details).length);
  }

  function stringifyJson(v) {
    try {
      return JSON.stringify(v == null ? {} : v, null, 2);
    } catch (e) {
      return String(v);
    }
  }

  function openDetails(item) {
    if (!detailModal || !detailBody) return;
    if (detailTitle) detailTitle.textContent = "Order details" + (item.symbol ? " - " + item.symbol : "");

    var parts = [];
    parts.push("Date: " + (item.date || ""));
    parts.push("Time: " + (item.ts || ""));
    parts.push("Symbol: " + (item.symbol || "-"));
    parts.push("Kind: " + (item.kind || "info"));
    if (item.pnl != null) parts.push("P&L: " + safeNumber(item.pnl).toFixed(2));
    parts.push("Message: " + (item.message || ""));

    var d = item.details || {};
    if (Object.keys(d).length) {
      parts.push("");
      parts.push("Fields:");
      if (d.action != null) parts.push("- action: " + d.action);
      if (d.order_type != null) parts.push("- order_type: " + d.order_type);
      if (d.qty != null) parts.push("- qty: " + d.qty);
      if (d.reason != null) parts.push("- reason: " + d.reason);
      if (d.entry_price != null) parts.push("- entry_price: " + d.entry_price);
      if (d.exit_price != null) parts.push("- exit_price: " + d.exit_price);
      if (d.initial_stop_price != null) parts.push("- initial_stop_price: " + d.initial_stop_price);
      if (d.initial_target_price != null) parts.push("- initial_target_price: " + d.initial_target_price);
      if (d.current_stop_price != null) parts.push("- current_stop_price: " + d.current_stop_price);
      if (d.current_target_price != null) parts.push("- current_target_price: " + d.current_target_price);
      if (d.new_stop_price != null) parts.push("- new_stop_price: " + d.new_stop_price);
      if (d.next_target_price != null) parts.push("- next_target_price: " + d.next_target_price);
      if (d.achieved_level != null) parts.push("- achieved_level: " + d.achieved_level);
      if (d.stop_price_at_exit != null) parts.push("- stop_price_at_exit: " + d.stop_price_at_exit);
      if (d.target_price_at_exit != null) parts.push("- target_price_at_exit: " + d.target_price_at_exit);

      if (d.request != null) {
        parts.push("");
        parts.push("Request:");
        parts.push(stringifyJson(d.request));
      }
      if (d.response != null) {
        parts.push("");
        parts.push("Response:");
        parts.push(stringifyJson(d.response));
      }
    }

    detailBody.textContent = parts.join("\n");
    detailModal.classList.remove("hidden");
    detailModal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
  }

  function closeDetails() {
    if (!detailModal) return;
    detailModal.classList.add("hidden");
    detailModal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
  }

  function render() {
    el.innerHTML = "";
    var lines = getMergedLines();
    populateSymbolOptions(lines);
    var mode = modeEl ? modeEl.value : "all";
    var filtered = getActiveFilteredLines(lines);
    updateSummary(lines, filtered, mode);
    updateTotalPnl(filtered);

    if (!filtered.length) {
      var row = document.createElement("div");
      row.className = "log-line log-line--muted";
      if (!lines.length) {
        row.textContent = "[—] No order log entries yet.";
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
      row.className = "log-line log-line--order" + (item.kind === "warn" ? " log-line--warn" : "");

      var text = document.createElement("span");
      text.className = "log-line__text";
      var symPart = item.symbol ? " [" + item.symbol + "]" : "";
      var pnlPart = item.pnl == null ? "" : " | P&L: " + safeNumber(item.pnl).toFixed(2);
      text.textContent = "[" + item.ts + "]" + symPart + " " + item.message + pnlPart;
      row.appendChild(text);

      if (hasDetails(item)) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn btn--ghost btn--sm log-line__detail-btn";
        btn.textContent = "Details";
        btn.addEventListener("click", function () {
          openDetails(item);
        });
        row.appendChild(btn);
      }

      el.appendChild(row);
    });
    el.scrollTop = el.scrollHeight;
  }

  function fetchServerOrders() {
    fetch("/api/orders")
      .then(function (r) {
        if (!r.ok) throw new Error(r.statusText);
        return r.json();
      })
      .then(function (data) {
        serverLines = Array.isArray(data.orders) ? data.orders : [];
        render();
      })
      .catch(function () {});
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
      if (!confirm("Clear all local order log entries in this browser?")) return;
      Dashboard.clearOrderLogs();
      if (window.Dashboard.toast) Dashboard.toast("Local order log cleared.");
      render();
    });
  }

  if (exportBtn) {
    exportBtn.addEventListener("click", function () {
      var lines = getMergedLines();
      var filtered = getActiveFilteredLines(lines);
      if (!filtered.length) {
        if (window.Dashboard.toast) Dashboard.toast("No order logs to export.", true);
        return;
      }
      var rows = ["date,time,iso,symbol,kind,pnl,message,action,order_type,qty,reason,request_json,response_json"];
      filtered.forEach(function (item) {
        var d = item.details || {};
        rows.push(
          [
            csvEscape(item.date || ""),
            csvEscape(item.ts || ""),
            csvEscape(item.iso || ""),
            csvEscape(item.symbol || ""),
            csvEscape(item.kind || "info"),
            csvEscape(item.pnl == null ? "" : safeNumber(item.pnl).toFixed(2)),
            csvEscape(item.message || ""),
            csvEscape(d.action || ""),
            csvEscape(d.order_type || ""),
            csvEscape(d.qty == null ? "" : d.qty),
            csvEscape(d.reason || ""),
            csvEscape(d.request == null ? "" : stringifyJson(d.request)),
            csvEscape(d.response == null ? "" : stringifyJson(d.response)),
          ].join(",")
        );
      });
      var stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      downloadCsv("order-log-" + stamp + ".csv", rows);
      if (window.Dashboard.toast) Dashboard.toast("Order log CSV downloaded.");
    });
  }

  if (detailBackdrop) detailBackdrop.addEventListener("click", closeDetails);
  if (detailClose) detailClose.addEventListener("click", closeDetails);
  if (detailCloseBtn) detailCloseBtn.addEventListener("click", closeDetails);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeDetails();
  });

  initRangeDefaults();
  updateFilterVisibility();
  render();
  fetchServerOrders();
  setInterval(fetchServerOrders, 3000);
})();
