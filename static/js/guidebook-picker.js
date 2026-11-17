// Searchable multi-select for guidebooks, with an "add new" dialog.
// The suggestion list itself comes from suggest.js (gr8Suggest).
//
// Progressive enhancement of <select name="guidebooks" multiple>: the select
// stays in the DOM (hidden) and is what gets submitted for existing guidebooks.
// The dialog's inputs live inside the same <form>, so a new guidebook is
// submitted as the new_guidebook* fields and created by the server.
(() => {
    const select = document.querySelector('select[name="guidebooks"]');
    const dialog = document.querySelector("[data-guidebook-dialog]");
    if (!select || !dialog || typeof dialog.showModal !== "function" || !window.gr8Suggest) {
        return; // fall back to the plain multi-select
    }

    const nameInput = dialog.querySelector('[name="new_guidebook"]');
    const dialogInputs = dialog.querySelectorAll("input");
    const addButton = dialog.querySelector("[data-guidebook-add]");
    const cancelButton = dialog.querySelector("[data-guidebook-cancel]");

    const options = Array.from(select.options);
    const norm = window.gr8Normalize;

    // --- markup -------------------------------------------------------------
    const root = document.createElement("div");
    root.className = "guidebook-picker";

    const chips = document.createElement("ul");
    chips.className = "guidebook-chips";

    const input = document.createElement("input");
    input.type = "search";
    input.placeholder = "Search guidebooks…";
    input.id = "guidebook-search";

    root.append(chips, input);
    select.hidden = true;
    select.after(root);
    const label = document.querySelector(`label[for="${select.id}"]`);
    if (label) {
        label.htmlFor = input.id;
    }

    // --- state --------------------------------------------------------------
    let confirmed = false; // a new guidebook was accepted with "Add guidebook"

    const hasNew = () => norm(nameInput.value) !== "";

    function renderChips() {
        chips.replaceChildren();
        const addChip = (text, onRemove, isNew) => {
            const li = document.createElement("li");
            li.className = isNew ? "is-new" : "";
            li.append(document.createTextNode(isNew ? `${text} (new)` : text));
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "chip-remove";
            remove.setAttribute("aria-label", `Remove ${text}`);
            remove.textContent = "×";
            remove.addEventListener("click", () => {
                onRemove();
                input.focus();
            });
            li.append(remove);
            chips.append(li);
        };
        options
            .filter((option) => option.selected)
            .forEach((option) =>
                addChip(option.textContent, () => {
                    option.selected = false;
                    renderChips();
                })
            );
        if (hasNew()) {
            addChip(nameInput.value.trim(), clearNew, true);
        }
    }

    function clearNew() {
        confirmed = false;
        dialogInputs.forEach((field) => {
            field.value = "";
        });
        renderChips();
    }

    function suggestions(text) {
        const query = norm(text);
        const items = gr8Match(
            options.filter((option) => !option.selected && option.value),
            (option) => option.textContent,
            text
        ).map((option) => ({ type: "option", option, text: option.textContent }));

        const exact = options.some((option) => norm(option.textContent) === query);
        if (!hasNew() && !exact) {
            items.push({
                type: "new",
                className: "is-add",
                text: query
                    ? `＋ Add new guidebook “${text.trim()}”…`
                    : "＋ Add new guidebook…",
            });
        }
        return items;
    }

    function choose(item) {
        if (item.type === "option") {
            item.option.selected = true;
            input.value = "";
            renderChips();
        } else {
            openDialog(input.value.trim());
        }
    }

    function openDialog(prefillName) {
        if (prefillName && !hasNew()) {
            nameInput.value = prefillName;
        }
        dialog.showModal();
        nameInput.focus();
    }

    gr8Suggest(input, {
        source: suggestions,
        onChoose: choose,
        showEmpty: true,
        emptyText: "No guidebooks found.",
        autoActivate: true,
        multiple: true,
    });

    // --- events -------------------------------------------------------------
    // Runs after the suggestion list's own key handling (registered first).
    input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault(); // never submit the crag form from here
        } else if (event.key === "Backspace" && !input.value) {
            const selected = options.filter((option) => option.selected);
            if (selected.length) {
                selected[selected.length - 1].selected = false;
                renderChips();
            }
        }
    });

    addButton.addEventListener("click", () => {
        nameInput.value = nameInput.value.trim();
        const invalid = Array.from(dialogInputs).find((field) => !field.checkValidity());
        if (!nameInput.value) {
            nameInput.setCustomValidity("Enter the name of the guidebook.");
            nameInput.reportValidity();
            nameInput.setCustomValidity("");
            return;
        }
        if (invalid) {
            invalid.reportValidity();
            return;
        }
        confirmed = true;
        input.value = "";
        renderChips();
        dialog.close();
    });

    cancelButton.addEventListener("click", () => {
        if (!confirmed) {
            clearNew();
        }
        dialog.close();
    });

    // Enter inside the dialog must not submit the whole crag form.
    dialog.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && event.target.tagName === "INPUT") {
            event.preventDefault();
            addButton.click();
        }
    });
    dialog.addEventListener("close", renderChips);

    // --- initial state ------------------------------------------------------
    confirmed = hasNew(); // values re-rendered by the server after a validation error
    renderChips();
    // Server-side validation error inside the dialog: reopen it so it is seen.
    if (dialog.querySelector('[aria-invalid="true"]')) {
        dialog.showModal();
    }
})();
