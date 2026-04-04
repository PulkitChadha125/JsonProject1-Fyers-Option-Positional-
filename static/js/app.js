(function () {
  const root = document.getElementById("symbol-settings-root");
  const emptyEl = document.getElementById("symbol-settings-empty");
  const appLog = document.getElementById("app-log");
  const btnAdd = document.getElementById("btn-add-setting");

  let headers = [];
  let rows = [];
  let tradingIndex = -1;

  function logApp(message, kind) {
    const line = document.createElement("div");
    line.className = "log-line" + (kind === "warn" ? " log-line--warn" : "");
    const t = new Date();
    const ts =
      String(t.getHours()).padStart(2, "0") +
      ":" +
      String(t.getMinutes()).padStart(2, "0") +
      ":" +
      String(t.getSeconds()).padStart(2, "0");
    line.textContent = "[" + ts + "] " + message;
    appLog.appendChild(line);
    appLog.scrollTop = appLog.scrollHeight;
  }

  function toast(msg, isErr) {
    let area = document.querySelector(".toast-area");
    if (!area) {
      area = document.createElement("div");
      area.className = "toast-area";
      document.body.appendChild(area);
    }
    const el = document.createElement("div");
    el.className = "toast" + (isErr ? " toast--err" : "");
    el.textContent = msg;
    area.appendChild(el);
    setTimeout(function () {
      el.remove();
    }, 4000);
  }

  function isTimeColumn(name) {
    const n = String(name || "")
      .trim()
      .toLowerCase();
    return n === "starttime" || n === "stoptime";
  }

  function parseTrading(val) {
    const v = String(val || "")
      .trim()
      .toUpperCase();
    return v === "TRUE" || v === "1" || v === "YES" || v === "ON";
  }

  function toTimeInputValue(raw) {
    const s = String(raw || "").trim();
    if (!s) return "";
    const parts = s.split(":");
    if (parts.length < 2) return "";
    let h = parseInt(parts[0], 10);
    let m = parseInt(parts[1], 10);
    if (Number.isNaN(h) || Number.isNaN(m)) return "";
    h = Math.min(23, Math.max(0, h));
    m = Math.min(59, Math.max(0, m));
    return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0");
  }

  function findTradingIndex(hdrs) {
    for (let i = 0; i < hdrs.length; i++) {
      if (String(hdrs[i]).trim().toUpperCase() === "TRADINGENABLED") return i;
    }
    return -1;
  }

  function labelForHeader(h, idx, hdrs) {
    const name = String(h).trim();
    const lower = name.toLowerCase();
    let dup = 0;
    for (let j = 0; j <= idx; j++) {
      if (String(hdrs[j]).trim().toLowerCase() === lower) dup++;
    }
    if (dup > 1 && lower === "starttime") return "Start time (" + dup + ")";
    return name || "Column " + (idx + 1);
  }

  function collectRowValues(card) {
    const idx = parseInt(card.getAttribute("data-row-index"), 10);
    const values = rows[idx] ? rows[idx].slice() : new Array(headers.length).fill("");
    const inputs = card.querySelectorAll("[data-col-index]");
    inputs.forEach(function (el) {
      const ci = parseInt(el.getAttribute("data-col-index"), 10);
      if (Number.isNaN(ci) || ci < 0 || ci >= headers.length) return;
      if (el.type === "time") values[ci] = el.value || "";
      else values[ci] = el.value;
    });
    const toggle = card.querySelector(".toggle-trading");
    if (toggle && tradingIndex >= 0) {
      values[tradingIndex] = toggle.classList.contains("is-on") ? "TRUE" : "FALSE";
    }
    return values;
  }

  function render() {
    root.innerHTML = "";
    if (!headers.length) {
      emptyEl.classList.remove("hidden");
      emptyEl.textContent =
        "No CSV headers found. Check TradeSettings.csv in the project folder.";
      return;
    }
    if (!rows.length) {
      emptyEl.classList.remove("hidden");
    } else {
      emptyEl.classList.add("hidden");
    }

    rows.forEach(function (row, rowIndex) {
      const card = document.createElement("div");
      card.className = "symbol-card";
      card.setAttribute("data-row-index", String(rowIndex));

      const symVal = row[0] != null ? String(row[0]) : "";
      const top = document.createElement("div");
      top.className = "symbol-card__top";
      const title = document.createElement("div");
      title.className = "symbol-card__title";
      title.textContent = symVal ? "Symbol: " + symVal : "Row " + (rowIndex + 1);
      const actions = document.createElement("div");
      actions.className = "symbol-card__actions";

      if (tradingIndex >= 0) {
        const on = parseTrading(row[tradingIndex]);
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "toggle-trading " + (on ? "is-on" : "is-off");
        toggle.textContent = on ? "Enabled" : "Disabled";
        toggle.setAttribute("aria-pressed", on ? "true" : "false");
        toggle.addEventListener("click", function () {
          const next = !toggle.classList.contains("is-on");
          fetch("/api/settings/" + rowIndex + "/trading", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: next }),
          })
            .then(function (r) {
              if (!r.ok) return r.json().then(function (j) {
                throw new Error(j.error || r.statusText);
              });
              return r.json();
            })
            .then(function () {
              toggle.classList.toggle("is-on", next);
              toggle.classList.toggle("is-off", !next);
              toggle.textContent = next ? "Enabled" : "Disabled";
              toggle.setAttribute("aria-pressed", next ? "true" : "false");
              if (rows[rowIndex]) rows[rowIndex][tradingIndex] = next ? "TRUE" : "FALSE";
              logApp("Trading " + (next ? "enabled" : "disabled") + " for row " + (rowIndex + 1));
            })
            .catch(function (e) {
              toast(e.message || "Toggle failed", true);
              logApp("Toggle failed: " + (e.message || "error"), "warn");
            });
        });
        actions.appendChild(toggle);
      }

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "btn btn--danger btn--sm";
      delBtn.textContent = "Delete";
      delBtn.addEventListener("click", function () {
        if (!confirm("Delete this setting row?")) return;
        fetch("/api/settings/" + rowIndex, { method: "DELETE" })
          .then(function (r) {
            if (!r.ok) return r.json().then(function (j) {
              throw new Error(j.error || r.statusText);
            });
            return r.json();
          })
          .then(function () {
            logApp("Deleted row " + (rowIndex + 1));
            loadSettings();
          })
          .catch(function (e) {
            toast(e.message || "Delete failed", true);
          });
      });
      actions.appendChild(delBtn);

      top.appendChild(title);
      top.appendChild(actions);
      card.appendChild(top);

      const grid = document.createElement("div");
      grid.className = "field-grid";

      headers.forEach(function (h, colIndex) {
        if (colIndex === tradingIndex) return;
        const field = document.createElement("div");
        field.className = "field";
        const lab = document.createElement("label");
        lab.setAttribute("for", "f-" + rowIndex + "-" + colIndex);
        lab.textContent = labelForHeader(h, colIndex, headers);
        const val = row[colIndex] != null ? String(row[colIndex]) : "";
        let input;
        if (isTimeColumn(h)) {
          input = document.createElement("input");
          input.type = "time";
          input.id = "f-" + rowIndex + "-" + colIndex;
          input.value = toTimeInputValue(val);
        } else {
          input = document.createElement("input");
          input.type = "text";
          input.id = "f-" + rowIndex + "-" + colIndex;
          input.value = val;
          input.autocomplete = "off";
        }
        input.setAttribute("data-col-index", String(colIndex));
        field.appendChild(lab);
        field.appendChild(input);
        grid.appendChild(field);
      });

      card.appendChild(grid);

      const foot = document.createElement("div");
      foot.className = "symbol-card__footer";
      const saveBtn = document.createElement("button");
      saveBtn.type = "button";
      saveBtn.className = "btn btn--ghost btn--sm";
      saveBtn.textContent = "Save row";
      saveBtn.addEventListener("click", function () {
        const values = collectRowValues(card);
        fetch("/api/settings/" + rowIndex, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ values: values }),
        })
          .then(function (r) {
            if (!r.ok) return r.json().then(function (j) {
              throw new Error(j.error || r.statusText);
            });
            return r.json();
          })
          .then(function (data) {
            rows[rowIndex] = data.row;
            toast("Saved row " + (rowIndex + 1));
            logApp("Saved settings for row " + (rowIndex + 1));
            render();
          })
          .catch(function (e) {
            toast(e.message || "Save failed", true);
          });
      });
      foot.appendChild(saveBtn);
      card.appendChild(foot);

      root.appendChild(card);
    });
  }

  function loadSettings() {
    return fetch("/api/settings")
      .then(function (r) {
        if (!r.ok) throw new Error(r.statusText);
        return r.json();
      })
      .then(function (data) {
        headers = data.headers || [];
        rows = data.rows || [];
        tradingIndex = findTradingIndex(headers);
        render();
      })
      .catch(function (e) {
        toast("Could not load settings: " + e.message, true);
        logApp("Load failed: " + e.message, "warn");
      });
  }

  btnAdd.addEventListener("click", function () {
    fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (j) {
          throw new Error(j.error || r.statusText);
        });
        return r.json();
      })
      .then(function () {
        logApp("Added new setting row");
        toast("New row added — fill fields and save.");
        loadSettings();
      })
      .catch(function (e) {
        toast(e.message || "Add failed", true);
      });
  });

  loadSettings();
})();
