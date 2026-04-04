(function () {
  var el = document.getElementById("app-log-page");
  var clearBtn = document.getElementById("app-log-clear");
  if (!el || !window.Dashboard) return;

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

  render();
})();
