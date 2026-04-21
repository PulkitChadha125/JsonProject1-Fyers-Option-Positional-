(function () {
  var el = document.getElementById("app-log-page");
  var clearBtn = document.getElementById("app-log-clear");
  var exportBtn = document.getElementById("app-log-export-csv");
  if (!el || !window.Dashboard) return;

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

  function render() {
    el.innerHTML = "";
    var lines = Dashboard.readAppLogs();
    if (!lines.length) {
      var row = document.createElement("div");
      row.className = "log-line log-line--muted";
      row.textContent = "[—] No app log entries yet. Use Symbol settings to record activity.";
      el.appendChild(row);
      return;
    }
    lines.forEach(function (item) {
      var row = document.createElement("div");
      row.className = "log-line" + (item.kind === "warn" ? " log-line--warn" : "");
      row.textContent = "[" + item.ts + "] " + item.message;
      el.appendChild(row);
    });
    el.scrollTop = el.scrollHeight;
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      if (!confirm("Clear all app log entries in this browser?")) return;
      Dashboard.clearAppLogs();
      if (window.Dashboard.toast) Dashboard.toast("App log cleared.");
      render();
    });
  }

  if (exportBtn) {
    exportBtn.addEventListener("click", function () {
      var lines = Dashboard.readAppLogs();
      if (!lines.length) {
        if (window.Dashboard.toast) Dashboard.toast("No app logs to export.", true);
        return;
      }
      var rows = ["date,time,iso,kind,message"];
      lines.forEach(function (item) {
        rows.push(
          [
            csvEscape(item.date || ""),
            csvEscape(item.ts || ""),
            csvEscape(item.iso || ""),
            csvEscape(item.kind || "info"),
            csvEscape(item.message || ""),
          ].join(",")
        );
      });
      var stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      downloadCsv("app-log-" + stamp + ".csv", rows);
      if (window.Dashboard.toast) Dashboard.toast("App log CSV downloaded.");
    });
  }

  render();
})();
