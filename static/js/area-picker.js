// Searchable area field for the crag form, with "add new area".
//
// Progressive enhancement of <select name="area"> plus the "new_area" text
// field: both stay in the form (hidden) and are what gets submitted. The text
// typed here is the truth: if it matches an existing area (ignoring case and
// accents), that area is selected; otherwise it is sent as a new area.
(() => {
    const root = document.querySelector("[data-area-picker]");
    if (!root || !window.gr8Suggest) {
        return;
    }
    const select = root.querySelector('select[name="area"]');
    const newInput = root.querySelector('input[name="new_area"]');
    if (!select || !newInput) {
        return;
    }
    const options = Array.from(select.options).filter((option) => option.value);
    const findArea = (text) =>
        options.find((option) => gr8Normalize(option.textContent) === gr8Normalize(text));

    // --- markup -------------------------------------------------------------
    const input = document.createElement("input");
    input.type = "search"; // same look as the guidebook picker
    input.id = "area-search";
    input.maxLength = newInput.maxLength > 0 ? newInput.maxLength : 200;
    input.placeholder = "Search or add an area…";
    // the area's help text and errors, plus new_area's errors (its help text is hidden)
    const newAreaErrors = (newInput.getAttribute("aria-describedby") || "")
        .split(" ")
        .filter((id) => id && !id.endsWith("_helptext"));
    const describedBy = [select.getAttribute("aria-describedby"), ...newAreaErrors]
        .filter(Boolean)
        .join(" ");
    if (select.getAttribute("aria-invalid") || newInput.getAttribute("aria-invalid")) {
        input.setAttribute("aria-invalid", "true");
    }

    const status = document.createElement("small");
    status.id = "area-search-status";
    status.setAttribute("aria-live", "polite");
    input.setAttribute("aria-describedby", [describedBy, status.id].filter(Boolean).join(" "));

    select.after(input);
    // the wrapper added by gr8Suggest() goes around the input, so add status after it
    const suggest = gr8Suggest(input, {
        showEmpty: true,
        emptyText: "No areas found.",
        source(text) {
            const items = gr8Match(options, (option) => option.textContent, text).map(
                (option) => ({ type: "area", text: option.textContent })
            );
            if (gr8Normalize(text) && !findArea(text)) {
                items.push({
                    type: "new",
                    text: `＋ Add new area “${text.trim()}”`,
                    className: "is-add",
                });
            }
            return items;
        },
        onChoose(item) {
            if (item.type === "area") {
                input.value = item.text;
            }
            sync();
        },
    });
    input.parentElement.after(status);

    // Hide the original controls; their error lists stay visible.
    select.hidden = true;
    newInput.hidden = true;
    root.querySelectorAll(`label[for="${newInput.id}"], #${newInput.id}_helptext`).forEach((el) => {
        el.hidden = true;
    });
    const label = root.querySelector(`label[for="${select.id}"]`);
    if (label) {
        label.htmlFor = input.id;
    }

    // --- state --------------------------------------------------------------
    function sync() {
        const text = input.value.trim().replace(/\s+/g, " ");
        const area = text && findArea(text);
        if (area) {
            select.value = area.value;
            newInput.value = "";
            status.textContent = "";
        } else if (text) {
            select.value = "";
            newInput.value = text;
            status.textContent = `New area “${text}” will be created.`;
        } else {
            select.value = "";
            newInput.value = "";
            status.textContent = "";
        }
    }

    input.addEventListener("input", sync);
    input.addEventListener("search", sync); // cleared with × or Escape
    input.addEventListener("keydown", (event) => {
        // Enter in this field never submits the crag form, it only confirms the text.
        if (event.key === "Enter") {
            event.preventDefault();
            sync();
            suggest.close();
        }
    });

    // --- initial state (also after a server-side validation error) ----------
    const selected = select.value && select.selectedOptions[0];
    input.value = selected ? selected.textContent : newInput.value;
    sync();
})();
