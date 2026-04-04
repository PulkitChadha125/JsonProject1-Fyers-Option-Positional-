(function () {
  var toggle = document.querySelector(".sidebar-toggle");
  var layout = document.querySelector(".layout");
  var overlay = document.getElementById("sidebar-overlay");
  if (!toggle || !layout) return;

  function setOpen(open) {
    layout.classList.toggle("layout--nav-open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (overlay) overlay.setAttribute("aria-hidden", open ? "false" : "true");
  }

  toggle.addEventListener("click", function () {
    setOpen(!layout.classList.contains("layout--nav-open"));
  });

  if (overlay) {
    overlay.addEventListener("click", function () {
      setOpen(false);
    });
  }

  layout.querySelectorAll(".nav-item").forEach(function (link) {
    link.addEventListener("click", function () {
      if (window.matchMedia("(max-width: 768px)").matches) setOpen(false);
    });
  });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (document.body.classList.contains("modal-open")) return;
    setOpen(false);
  });
})();
