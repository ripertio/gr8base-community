(function () {
  var button = document.getElementById("filters-button");
  var panel = document.getElementById("filters-panel");
  var flag = document.getElementById("filters-flag");
  if (!button || !panel) return;

  button.addEventListener("click", function () {
    var open = panel.hidden;
    panel.hidden = !open;
    button.classList.toggle("is-open", open);
    button.setAttribute("aria-expanded", open ? "true" : "false");
    // Remember the open state across form submits.
    if (flag) flag.disabled = !open;
  });
})();
