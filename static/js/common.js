(function (global) {
  var APP_LOG_KEY = "jsonproject1_app_log_v1";
  var ORDER_LOG_KEY = "jsonproject1_order_log_v1";
  var MAX_LINES = 400;

  function formatDateKey(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }

  function migrateLine(line) {
    if (!line || typeof line !== "object") return null;
    var out = {
      ts: line.ts != null ? String(line.ts) : "00:00:00",
      message: line.message != null ? String(line.message) : "",
      kind: line.kind || "info",
    };
    if (line.iso && typeof line.iso === "string") {
      out.iso = line.iso;
      out.date = line.date && typeof line.date === "string" ? line.date : line.iso.slice(0, 10);
    } else if (line.date && typeof line.date === "string") {
      out.date = line.date;
      out.iso = line.date + "T12:00:00.000Z";
    } else {
      out.date = "2000-01-01";
      out.iso = "2000-01-01T12:00:00.000Z";
    }
    out.symbol = line.symbol != null ? String(line.symbol).trim() : "";
    return out;
  }

  function readLines(key) {
    try {
      var raw = global.localStorage.getItem(key);
      if (!raw) return [];
      var parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.map(migrateLine).filter(Boolean);
    } catch (e) {
      return [];
    }
  }

  function writeLines(key, lines) {
    try {
      global.localStorage.setItem(key, JSON.stringify(lines.slice(-MAX_LINES)));
    } catch (e) {
      /* ignore quota */
    }
  }

  function pushLine(key, message, kind, meta) {
    meta = meta || {};
    var lines = readLines(key);
    var t = new Date();
    var ts =
      String(t.getHours()).padStart(2, "0") +
      ":" +
      String(t.getMinutes()).padStart(2, "0") +
      ":" +
      String(t.getSeconds()).padStart(2, "0");
    lines.push({
      ts: ts,
      message: message,
      kind: kind || "info",
      date: formatDateKey(t),
      iso: t.toISOString(),
      symbol: meta.symbol != null ? String(meta.symbol).trim() : "",
    });
    writeLines(key, lines);
  }

  global.Dashboard = {
    toast: function (msg, isErr) {
      var area = document.querySelector(".toast-area");
      if (!area) {
        area = document.createElement("div");
        area.className = "toast-area";
        document.body.appendChild(area);
      }
      var el = document.createElement("div");
      el.className = "toast" + (isErr ? " toast--err" : "");
      el.textContent = msg;
      area.appendChild(el);
      setTimeout(function () {
        el.remove();
      }, 4000);
    },

    appendAppLog: function (message, kind) {
      pushLine(APP_LOG_KEY, message, kind, {});
    },

    readAppLogs: function () {
      return readLines(APP_LOG_KEY);
    },

    clearAppLogs: function () {
      writeLines(APP_LOG_KEY, []);
    },

    /** @param {string} [symbol] - optional symbol for order-log filters */
    appendOrderLog: function (message, kind, symbol) {
      pushLine(ORDER_LOG_KEY, message, kind, { symbol: symbol });
    },

    readOrderLogs: function () {
      return readLines(ORDER_LOG_KEY);
    },

    clearOrderLogs: function () {
      writeLines(ORDER_LOG_KEY, []);
    },
  };
})(typeof window !== "undefined" ? window : this);
