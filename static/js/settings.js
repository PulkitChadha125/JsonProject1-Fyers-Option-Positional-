(function () {
  var thead = document.getElementById("settings-thead");
  var tbody = document.getElementById("settings-tbody");
  var emptyEl = document.getElementById("settings-empty");
  var tableEl = document.getElementById("settings-table");
  var btnAdd = document.getElementById("btn-add-setting");
  var btnLoad = document.getElementById("btn-load-set");

  var modal = document.getElementById("edit-modal");
  var modalBackdrop = document.getElementById("edit-modal-backdrop");
  var modalClose = document.getElementById("edit-modal-close");
  var modalCancel = document.getElementById("edit-modal-cancel");
  var modalSave = document.getElementById("edit-modal-save");
  var modalDelete = document.getElementById("edit-modal-delete");
  var modalForm = document.getElementById("edit-modal-form");
  var modalSubtitle = document.getElementById("edit-modal-subtitle");

  var headers = [];
  var rows = [];
  var tradingIndex = -1;
  var modalRowIndex = null;
  var draftRow = null;

  function logApp(message, kind) {
    if (window.Dashboard && Dashboard.appendAppLog) {
      Dashboard.appendAppLog(message, kind);
    }
  }

  function logOrder(message, kind, row) {
    if (!window.Dashboard || !Dashboard.appendOrderLog) return;
    var sym = "";
    if (row && row.length && row[0] != null) sym = String(row[0]).trim();
    Dashboard.appendOrderLog(message, kind, sym);
  }

  function toast(msg, isErr) {
    if (window.Dashboard && Dashboard.toast) Dashboard.toast(msg, isErr);
  }

  function normalizeHeaderName(name) {
    return String(name || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]/g, "");
  }

  function isTimeColumn(name) {
    var n = normalizeHeaderName(name);
    // Supports StartTime/StopTime and variants like TimeRage1/TimeRange2.
    return n.indexOf("time") !== -1;
  }

  function parseTrading(val) {
    var v = String(val || "")
      .trim()
      .toUpperCase();
    return v === "TRUE" || v === "1" || v === "YES" || v === "ON";
  }

  function isExpTypeColumn(name) {
    var n = normalizeHeaderName(name);
    return n === "exptype";
  }

  function isExpiryDateColumn(name) {
    var n = normalizeHeaderName(name);
    return n === "expierydate" || n === "expirydate";
  }

  function toDateInputValue(raw) {
    var s = String(raw || "").trim();
    if (!s) return "";
    var m;
    m = s.match(/^(\d{2})-(\d{2})-(\d{4})$/);
    if (m) return m[3] + "-" + m[2] + "-" + m[1];
    m = s.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
    if (m) return m[3] + "-" + m[2] + "-" + m[1];
    m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (m) return s;
    return "";
  }

  function fromDateInputValue(raw) {
    var s = String(raw || "").trim();
    if (!s) return "";
    var m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) return s;
    return m[3] + "-" + m[2] + "-" + m[1];
  }

  function toTimeInputValue(raw) {
    var s = String(raw || "").trim();
    if (!s) return "";
    var parts = s.split(":");
    if (parts.length < 2) return "";
    var h = parseInt(parts[0], 10);
    var m = parseInt(parts[1], 10);
    if (isNaN(h) || isNaN(m)) return "";
    h = Math.min(23, Math.max(0, h));
    m = Math.min(59, Math.max(0, m));
    return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0");
  }

  function findTradingIndex(hdrs) {
    for (var i = 0; i < hdrs.length; i++) {
      if (String(hdrs[i]).trim().toUpperCase() === "TRADINGENABLED") return i;
    }
    return -1;
  }

  function headerLabel(h, idx, hdrs) {
    var name = String(h).trim();
    var lower = normalizeHeaderName(name);
    var dup = 0;
    for (var j = 0; j <= idx; j++) {
      if (normalizeHeaderName(hdrs[j]) === lower) dup++;
    }
    if (dup > 1) return (name || "Column " + (idx + 1)) + " (" + dup + ")";
    return name || "Column " + (idx + 1);
  }

  /** Column indices shown after pinned Symbol + Trading + Actions (excludes TRADINGENABLED duplicate). */
  function getTailColumnIndices() {
    var out = [];
    for (var i = 1; i < headers.length; i++) {
      if (i === tradingIndex) continue;
      out.push(i);
    }
    return out;
  }

  function closeModal() {
    if (!modal) return;
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
    modalRowIndex = null;
    draftRow = null;
    if (modalForm) modalForm.innerHTML = "";
    document.body.classList.remove("modal-open");
  }

  function openModal(rowIndex) {
    if (!modal || !rows[rowIndex]) return;
    modalRowIndex = rowIndex;
    draftRow = rows[rowIndex].slice();
    var sym = draftRow[0] != null ? String(draftRow[0]).trim() : "";
    var titleEl = document.getElementById("edit-modal-title");
    if (titleEl) {
      titleEl.textContent = sym ? "Edit: " + sym : "Edit symbol setting";
    }
    if (modalSubtitle) {
      modalSubtitle.textContent = "Adjust fields and click Save to update TradeSettings.csv.";
    }
    buildModalForm();
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
  }

  function buildModalForm() {
    if (!modalForm || !draftRow) return;
    modalForm.innerHTML = "";

    for (var ci = 0; ci < headers.length; ci++) {
      var field = document.createElement("div");
      field.className = "modal-field";

      var lab = document.createElement("label");
      lab.className = "modal-field__label";
      lab.setAttribute("for", "mf-" + ci);
      lab.textContent = headerLabel(headers[ci], ci, headers);

      if (ci === tradingIndex) {
        field.classList.add("modal-field--full");
        var row = document.createElement("div");
        row.className = "modal-field__trading";
        var on = parseTrading(draftRow[ci]);
        var tbtn = document.createElement("button");
        tbtn.type = "button";
        tbtn.id = "mf-" + ci;
        tbtn.className = "btn-trade-toggle modal-trade-toggle " + (on ? "is-on" : "is-off");
        tbtn.setAttribute("aria-pressed", on ? "true" : "false");
        tbtn.innerHTML =
          '<span class="btn-trade-toggle__icon" aria-hidden="true">▶</span>';
        var hint = document.createElement("span");
        hint.className = "modal-field__trading-text";
        hint.textContent = on ? "Trading enabled" : "Trading disabled";
        tbtn.addEventListener("click", function () {
          var next = !parseTrading(draftRow[tradingIndex]);
          draftRow[tradingIndex] = next ? "TRUE" : "FALSE";
          tbtn.classList.toggle("is-on", next);
          tbtn.classList.toggle("is-off", !next);
          tbtn.setAttribute("aria-pressed", next ? "true" : "false");
          hint.textContent = next ? "Trading enabled" : "Trading disabled";
        });
        row.appendChild(tbtn);
        row.appendChild(hint);
        field.appendChild(lab);
        field.appendChild(row);
        modalForm.appendChild(field);
        continue;
      }

      var input;
      if (isTimeColumn(headers[ci])) {
        input = document.createElement("input");
        input.type = "time";
        input.className = "modal-input";
        input.id = "mf-" + ci;
        input.value = toTimeInputValue(draftRow[ci]);
      } else if (isExpTypeColumn(headers[ci])) {
        input = document.createElement("select");
        input.className = "modal-input";
        input.id = "mf-" + ci;
        var optBlank = document.createElement("option");
        optBlank.value = "";
        optBlank.textContent = "Select ExpType";
        input.appendChild(optBlank);
        ["WEEKLY", "MONTHLY"].forEach(function (v) {
          var opt = document.createElement("option");
          opt.value = v;
          opt.textContent = v;
          input.appendChild(opt);
        });
        var current = draftRow[ci] != null ? String(draftRow[ci]).trim().toUpperCase() : "";
        input.value = current === "WEEKLY" || current === "MONTHLY" ? current : "";
      } else if (isExpiryDateColumn(headers[ci])) {
        input = document.createElement("input");
        input.type = "date";
        input.className = "modal-input";
        input.id = "mf-" + ci;
        input.value = toDateInputValue(draftRow[ci]);
      } else {
        input = document.createElement("input");
        input.type = "text";
        input.className = "modal-input";
        input.id = "mf-" + ci;
        input.value = draftRow[ci] != null ? String(draftRow[ci]) : "";
        input.autocomplete = "off";
      }
      input.setAttribute("data-col-index", String(ci));
      field.appendChild(lab);
      field.appendChild(input);
      modalForm.appendChild(field);
    }
  }

  function syncDraftFromModal() {
    if (!modalForm || !draftRow) return;
    modalForm.querySelectorAll("input[data-col-index]").forEach(function (el) {
      var ci = parseInt(el.getAttribute("data-col-index"), 10);
      if (isNaN(ci) || ci < 0 || ci >= headers.length) return;
      if (ci === tradingIndex) return;
      if (el.type === "time") {
        draftRow[ci] = el.value || "";
      } else if (el.type === "date" && isExpiryDateColumn(headers[ci])) {
        draftRow[ci] = fromDateInputValue(el.value || "");
      } else {
        draftRow[ci] = el.value;
      }
    });
    var tbtn = modalForm.querySelector(".modal-trade-toggle");
    if (tbtn && tradingIndex >= 0 && tradingIndex < draftRow.length) {
      draftRow[tradingIndex] = tbtn.classList.contains("is-on") ? "TRUE" : "FALSE";
    }
  }

  function saveModal() {
    if (modalRowIndex === null || !draftRow) return;
    syncDraftFromModal();
    fetch("/api/settings/" + modalRowIndex, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values: draftRow }),
    })
      .then(function (r) {
        if (!r.ok)
          return r.json().then(function (j) {
            throw new Error(j.error || r.statusText);
          });
        return r.json();
      })
      .then(function (data) {
        rows[modalRowIndex] = data.row;
        logApp("Saved settings for row " + (modalRowIndex + 1));
        logOrder("Symbol settings saved", "info", data.row);
        toast("Saved to TradeSettings.csv");
        closeModal();
        render();
      })
      .catch(function (e) {
        toast(e.message || "Save failed", true);
      });
  }

  function deleteRow(rowIndex) {
    if (!confirm("Delete this symbol setting row?")) return;
    var snapshot = rows[rowIndex] ? rows[rowIndex].slice() : [];
    fetch("/api/settings/" + rowIndex, { method: "DELETE" })
      .then(function (r) {
        if (!r.ok)
          return r.json().then(function (j) {
            throw new Error(j.error || r.statusText);
          });
        return r.json();
      })
      .then(function () {
        logApp("Deleted row " + (rowIndex + 1));
        logOrder("Symbol setting row deleted", "info", snapshot);
        closeModal();
        loadSettings();
      })
      .catch(function (e) {
        toast(e.message || "Delete failed", true);
      });
  }

  function renderHeader() {
    thead.innerHTML = "";
    var tr = document.createElement("tr");
    var th0 = document.createElement("th");
    th0.className = "th-pin th-pin--1";
    th0.textContent = headerLabel(headers[0], 0, headers).toUpperCase();
    tr.appendChild(th0);

    var thT = document.createElement("th");
    thT.className = "th-pin th-pin--2 th-toggle";
    thT.textContent = "TRADING";
    tr.appendChild(thT);

    var thA = document.createElement("th");
    thA.className = "th-pin th-pin--3 th-actions";
    thA.textContent = "ACTIONS";
    tr.appendChild(thA);

    getTailColumnIndices().forEach(function (i) {
      var th = document.createElement("th");
      th.className = "th-scroll";
      th.textContent = headerLabel(headers[i], i, headers).toUpperCase();
      tr.appendChild(th);
    });
    thead.appendChild(tr);
  }

  function renderCellView(row, colIndex) {
    var td = document.createElement("td");
    td.className = "td-scroll";
    var v = row[colIndex] != null ? String(row[colIndex]) : "";
    td.textContent = v;
    td.title = v;
    return td;
  }

  function attachToggleButton(tdToggle, rowIndex) {
    tdToggle.innerHTML = "";
    var on = rows[rowIndex] && tradingIndex >= 0 && parseTrading(rows[rowIndex][tradingIndex]);
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn-trade-toggle " + (on ? "is-on" : "is-off");
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.setAttribute(
      "aria-label",
      on ? "Trading enabled; click to disable" : "Trading disabled; click to enable"
    );
    btn.innerHTML = '<span class="btn-trade-toggle__icon" aria-hidden="true">▶</span>';
    btn.addEventListener("click", function () {
      var next = !parseTrading(rows[rowIndex][tradingIndex]);
      fetch("/api/settings/" + rowIndex + "/trading", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: next }),
      })
        .then(function (r) {
          if (!r.ok)
            return r.json().then(function (j) {
              throw new Error(j.error || r.statusText);
            });
          return r.json();
        })
        .then(function () {
          if (rows[rowIndex]) rows[rowIndex][tradingIndex] = next ? "TRUE" : "FALSE";
          logApp("Trading " + (next ? "enabled" : "disabled") + " for row " + (rowIndex + 1));
          logOrder("Trading " + (next ? "enabled" : "disabled"), "info", rows[rowIndex]);
          render();
        })
        .catch(function (e) {
          toast(e.message || "Toggle failed", true);
        });
    });
    tdToggle.appendChild(btn);
  }

  function renderActionsCell(rowIndex) {
    var td = document.createElement("td");
    td.className = "td-actions td-pin td-pin--3";

    var wrap = document.createElement("div");
    wrap.className = "action-group";

    var edit = document.createElement("button");
    edit.type = "button";
    edit.className = "btn-icon btn-icon--edit";
    edit.setAttribute("title", "Edit");
    edit.setAttribute("aria-label", "Edit row");
    edit.innerHTML =
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>';
    edit.addEventListener("click", function () {
      openModal(rowIndex);
    });

    var del = document.createElement("button");
    del.type = "button";
    del.className = "btn-icon btn-icon--delete";
    del.setAttribute("title", "Delete");
    del.setAttribute("aria-label", "Delete row");
    del.innerHTML =
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>';
    del.addEventListener("click", function () {
      deleteRow(rowIndex);
    });

    wrap.appendChild(edit);
    wrap.appendChild(del);
    td.appendChild(wrap);
    return td;
  }

  function updateSchemaHint() {
    var el = document.getElementById("schema-hint");
    if (!el) return;
    if (!headers.length) {
      el.setAttribute("hidden", "");
      el.textContent = "";
      return;
    }
    el.removeAttribute("hidden");
    var text = "Columns from CSV: " + headers.join(", ");
    el.textContent = text;
    el.title = text;
  }

  function render() {
    tbody.innerHTML = "";
    if (!headers.length) {
      thead.innerHTML = "";
      emptyEl.classList.remove("hidden");
      emptyEl.textContent =
        "No CSV headers found. Check TradeSettings.csv in the project folder.";
      tableEl.classList.add("hidden");
      updateSchemaHint();
      return;
    }
    tableEl.classList.remove("hidden");

    if (!rows.length) {
      emptyEl.classList.remove("hidden");
    } else {
      emptyEl.classList.add("hidden");
    }

    renderHeader();

    rows.forEach(function (row, rowIndex) {
      var tr = document.createElement("tr");
      tr.setAttribute("data-row-index", String(rowIndex));

      var td0 = document.createElement("td");
      td0.className = "td-pin td-pin--1";
      var v0 = row[0] != null ? String(row[0]) : "";
      td0.textContent = v0;
      td0.title = v0;
      tr.appendChild(td0);

      var tdToggle = document.createElement("td");
      tdToggle.className = "td-toggle td-pin td-pin--2";
      if (tradingIndex >= 0) attachToggleButton(tdToggle, rowIndex);
      else tdToggle.textContent = "—";
      tr.appendChild(tdToggle);

      tr.appendChild(renderActionsCell(rowIndex));

      getTailColumnIndices().forEach(function (ci) {
        tr.appendChild(renderCellView(row, ci));
      });
      tbody.appendChild(tr);
    });
    updateSchemaHint();
  }

  function loadSettings(options) {
    options = options || {};
    if (!options.keepModal) closeModal();
    return fetch("/api/settings")
      .then(function (r) {
        if (!r.ok) throw new Error(r.statusText);
        return r.json();
      })
      .then(function (data) {
        headers = data.headers || [];
        rows = data.rows || [];
        tradingIndex = findTradingIndex(headers);
        if (modalRowIndex !== null && modalRowIndex >= rows.length) {
          closeModal();
        }
        render();
        return true;
      })
      .catch(function (e) {
        toast("Could not load settings: " + e.message, true);
        logApp("Load failed: " + e.message, "warn");
        return false;
      });
  }

  if (btnLoad) {
    btnLoad.addEventListener("click", function () {
      loadSettings().then(function (ok) {
        if (!ok) return;
        logApp("Reloaded settings from TradeSettings.csv");
        toast("Loaded latest from TradeSettings.csv");
      });
    });
  }

  if (btnAdd) {
    btnAdd.addEventListener("click", function () {
      fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      })
        .then(function (r) {
          if (!r.ok)
            return r.json().then(function (j) {
              throw new Error(j.error || r.statusText);
            });
          return r.json();
        })
        .then(function () {
          logApp("Added new symbol setting row");
          return loadSettings({ keepModal: true });
        })
        .then(function (ok) {
          if (!ok) return;
          if (rows.length) {
            logOrder("New symbol setting row created", "info", rows[rows.length - 1]);
            openModal(rows.length - 1);
          }
          toast("New row added — edit in the dialog and Save.");
        })
        .catch(function (e) {
          toast(e.message || "Add failed", true);
        });
    });
  }

  if (modalBackdrop)
    modalBackdrop.addEventListener("click", function () {
      closeModal();
    });
  if (modalClose) modalClose.addEventListener("click", closeModal);
  if (modalCancel) modalCancel.addEventListener("click", closeModal);
  if (modalSave) modalSave.addEventListener("click", saveModal);
  if (modalDelete) {
    modalDelete.addEventListener("click", function () {
      if (modalRowIndex !== null) deleteRow(modalRowIndex);
    });
  }

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && modal && !modal.classList.contains("hidden")) {
      closeModal();
    }
  });

  var posTbody = document.getElementById("net-positions-tbody");
  var posEmpty = document.getElementById("net-positions-empty");
  var posTable = document.getElementById("net-positions-table");
  var strategyBadge = document.getElementById("strategy-status-badge");
  var strategyConn = document.getElementById("strategy-conn-line");
  var btnStrategyStart = document.getElementById("btn-strategy-start");
  var btnStrategyStop = document.getElementById("btn-strategy-stop");
  var posPollTimer = null;
  var statusPollTimer = null;
  var strategyRunningFlag = false;

  function applyStrategyStatus(st) {
    if (!strategyBadge) return;
    strategyRunningFlag = !!st.running;
    var running = !!st.running;
    var connected = !!st.connected;
    strategyBadge.classList.remove("badge--live", "badge--warn", "badge--neutral");
    if (running && connected) {
      strategyBadge.textContent = "Strategy: Running";
      strategyBadge.setAttribute("data-state", "running");
      strategyBadge.classList.add("badge--live");
    } else if (running && !connected) {
      strategyBadge.textContent = "Strategy: Running · Not connected";
      strategyBadge.setAttribute("data-state", "degraded");
      strategyBadge.classList.add("badge--warn");
    } else {
      strategyBadge.textContent = "Strategy: Stopped";
      strategyBadge.setAttribute("data-state", "stopped");
      strategyBadge.classList.add("badge--neutral");
    }
    if (strategyConn) {
      if (st.message) {
        strategyConn.hidden = false;
        strategyConn.textContent = st.message;
      } else {
        strategyConn.hidden = true;
        strategyConn.textContent = "";
      }
    }
    if (btnStrategyStart) btnStrategyStart.disabled = running;
    if (btnStrategyStop) btnStrategyStop.disabled = !running;
  }

  function renderNetPositions(list) {
    if (!posTbody) return;
    posTbody.innerHTML = "";
    if (!list || !list.length) {
      if (posEmpty) {
        posEmpty.classList.remove("hidden");
        posEmpty.textContent = strategyRunningFlag
          ? "No open net positions from Fyers for this poll."
          : "No open positions. Start the strategy (Fyers session required) to load live data.";
      }
      if (posTable) posTable.classList.add("hidden");
      return;
    }
    if (posEmpty) posEmpty.classList.add("hidden");
    if (posTable) posTable.classList.remove("hidden");

    list.forEach(function (p) {
      var tr = document.createElement("tr");
      var tdTs = document.createElement("td");
      tdTs.className = "td-mono td-wrap";
      tdTs.textContent = p.timestamp != null ? String(p.timestamp) : "";

      var tdSym = document.createElement("td");
      tdSym.className = "td-wrap";
      tdSym.textContent = p.symbolname != null ? String(p.symbolname) : "";

      var tdR = document.createElement("td");
      tdR.className = "td-mono";
      tdR.textContent = p.realisedpnl != null ? String(p.realisedpnl) : "";

      var tdPct = document.createElement("td");
      tdPct.className = "td-mono";
      tdPct.textContent = p.unrealisedpnl_pct != null ? String(p.unrealisedpnl_pct) : "";

      var tdPts = document.createElement("td");
      tdPts.className = "td-mono";
      tdPts.textContent = p.unrealisedpnl_pts != null ? String(p.unrealisedpnl_pts) : "";

      var tdSl = document.createElement("td");
      tdSl.className = "td-mono";
      tdSl.textContent = p.currentsl != null ? String(p.currentsl) : "";

      var tdTgt = document.createElement("td");
      tdTgt.className = "td-mono";
      tdTgt.textContent = p.currenttarget != null ? String(p.currenttarget) : "";

      var tdAct = document.createElement("td");
      tdAct.className = "td-actions-narrow";
      var exitBtn = document.createElement("button");
      exitBtn.type = "button";
      exitBtn.className = "btn-icon btn-icon--exit btn-exit-position";
      exitBtn.setAttribute("data-position-id", p.id || "");
      exitBtn.setAttribute("title", "Exit / hide from list");
      exitBtn.setAttribute("aria-label", "Exit position");
      exitBtn.innerHTML =
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>';
      tdAct.appendChild(exitBtn);

      tr.appendChild(tdTs);
      tr.appendChild(tdSym);
      tr.appendChild(tdR);
      tr.appendChild(tdPct);
      tr.appendChild(tdPts);
      tr.appendChild(tdSl);
      tr.appendChild(tdTgt);
      tr.appendChild(tdAct);
      posTbody.appendChild(tr);
    });
  }

  function fetchStrategyStatusOnly() {
    fetch("/api/strategy/status")
      .then(function (r) {
        return r.json();
      })
      .then(applyStrategyStatus)
      .catch(function () {});
  }

  function fetchNetPositionsBundle() {
    fetch("/api/net-positions")
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        applyStrategyStatus(data);
        renderNetPositions(data.positions || []);
      })
      .catch(function () {});
  }

  function startPositionPolling() {
    if (posPollTimer) clearInterval(posPollTimer);
    posPollTimer = setInterval(fetchNetPositionsBundle, 2000);
  }

  function stopPositionPolling() {
    if (posPollTimer) {
      clearInterval(posPollTimer);
      posPollTimer = null;
    }
  }

  if (btnStrategyStart) {
    btnStrategyStart.addEventListener("click", function () {
      fetch("/api/strategy/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      })
        .then(function (r) {
          return r.json().then(function (j) {
            return { ok: r.ok, j: j };
          });
        })
        .then(function (x) {
          applyStrategyStatus(x.j);
          if (x.ok) {
            logApp("Strategy started");
            toast(x.j.message || "Strategy started");
            startPositionPolling();
            fetchNetPositionsBundle();
          } else {
            toast(x.j.message || "Could not start strategy", true);
            logApp("Strategy start failed: " + (x.j.message || ""), "warn");
          }
        })
        .catch(function (e) {
          toast(e.message || "Start failed", true);
        });
    });
  }

  if (btnStrategyStop) {
    btnStrategyStop.addEventListener("click", function () {
      fetch("/api/strategy/stop", { method: "POST" })
        .then(function (r) {
          return r.json();
        })
        .then(function (data) {
          stopPositionPolling();
          applyStrategyStatus(data);
          renderNetPositions([]);
          if (posEmpty) {
            posEmpty.classList.remove("hidden");
            posEmpty.textContent =
              "No open positions. Start the strategy (Fyers session required) to load live data.";
          }
          if (posTable) posTable.classList.add("hidden");
          logApp("Strategy stopped");
          toast(data.message || "Strategy stopped");
        })
        .catch(function (e) {
          toast(e.message || "Stop failed", true);
        });
    });
  }

  if (posTbody) {
    posTbody.addEventListener("click", function (e) {
      var btn = e.target.closest(".btn-exit-position");
      if (!btn) return;
      var pid = btn.getAttribute("data-position-id");
      if (!pid) return;
      if (!confirm("Hide this position from the live list? Square off in Fyers if you still hold it.")) return;
      fetch("/api/net-positions/" + encodeURIComponent(pid) + "/exit", { method: "POST" })
        .then(function (r) {
          return r.json().then(function (j) {
            return { ok: r.ok, j: j };
          });
        })
        .then(function (x) {
          applyStrategyStatus(x.j);
          renderNetPositions(x.j.positions || []);
          toast(x.j.message || (x.ok ? "Updated" : "Failed"), !x.ok);
          if (window.Dashboard && Dashboard.appendOrderLog) {
            Dashboard.appendOrderLog("Position exit (dashboard): " + pid, "info", "");
          }
        })
        .catch(function (err) {
          toast(err.message || "Exit failed", true);
        });
    });
  }

  fetch("/api/strategy/status")
    .then(function (r) {
      return r.json();
    })
    .then(function (st) {
      applyStrategyStatus(st);
      if (st.running) {
        startPositionPolling();
        fetchNetPositionsBundle();
      } else {
        renderNetPositions([]);
      }
    })
    .catch(function () {
      renderNetPositions([]);
    });

  if (statusPollTimer) clearInterval(statusPollTimer);
  statusPollTimer = setInterval(fetchStrategyStatusOnly, 5000);

  logApp("Dashboard: symbol settings page loaded.");
  loadSettings();
})();

