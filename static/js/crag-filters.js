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

// Multi-select dropdowns (area, aspect): <details class="dropdown" data-multi-select>
// with checkboxes. Ticking does not reload the list (the panel's onchange skips
// these); the list reloads once when the dropdown closes, if anything changed.
(function () {
  var dropdowns = Array.prototype.slice.call(
    document.querySelectorAll("details[data-multi-select]")
  );
  if (!dropdowns.length) return;

  function checkedValues(details) {
    return Array.prototype.slice
      .call(details.querySelectorAll("input[type=checkbox]:checked"))
      .map(function (box) { return box.value; })
      .join("\n");
  }

  dropdowns.forEach(function (details) {
    var shown = details.querySelector("[data-multi-select-value]");
    var before = checkedValues(details);

    // "South-East, South" or the empty text, like the server renders it
    details.addEventListener("change", function () {
      var labels = Array.prototype.slice
        .call(details.querySelectorAll("input[type=checkbox]:checked"))
        .map(function (box) { return box.closest("label").textContent.trim(); });
      shown.textContent = labels.length ? labels.join(", ") : details.dataset.empty;
    });

    details.addEventListener("toggle", function () {
      if (details.open) {
        before = checkedValues(details);
        // only one open at a time
        dropdowns.forEach(function (other) {
          if (other !== details) other.open = false;
        });
      } else if (checkedValues(details) !== before) {
        details.closest("form").submit();
      }
    });

    details.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && details.open) {
        event.preventDefault();
        details.open = false;
        details.querySelector("summary").focus();
      }
    });
  });

  // a click outside an open dropdown closes it (and so applies the choice)
  document.addEventListener("click", function (event) {
    dropdowns.forEach(function (details) {
      if (details.open && !details.contains(event.target)) details.open = false;
    });
  });
})();
