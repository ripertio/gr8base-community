// Searchable multi-select for guidebooks, with an "add new" dialog.
//
// Progressive enhancement of <select name="guidebooks" multiple>: the select
// stays in the DOM (hidden) and is what gets submitted for existing guidebooks.
// The dialog's inputs live inside the same <form>, so a new guidebook is
// submitted as the new_guidebook* fields and created by the server.
(() => {
    const select = document.querySelector('select[name="guidebooks"]');
    const dialog = document.querySelector("[data-guidebook-dialog]");
    if (!select || !dialog || typeof dialog.showModal !== "function") {
        return; // fall back to the plain multi-select
    }

    const nameInput = dialog.querySelector('[name="new_guidebook"]');
    const dialogInputs = dialog.querySelectorAll("input");
    const addButton = dialog.querySelector("[data-guidebook-add]");
    const cancelButton = dialog.querySelector("[data-guidebook-cancel]");

    const options = Array.from(select.options);
    const norm = (text) => text.trim().replace(/\s+/g, " ").toLowerCase();

    // --- markup -------------------------------------------------------------
    const root = document.createElement("div");
    root.className = "guidebook-picker";

    const chips = document.createElement("ul");
    chips.className = "guidebook-chips";

    const input = document.createElement("input");
    input.type = "search";
    input.autocomplete = "off";
    input.placeholder = "Search guidebooks…";
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-controls", "guidebook-listbox");
    input.id = "guidebook-search";

    const list = document.createElement("ul");
    list.id = "guidebook-listbox";
    list.className = "guidebook-options";
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-multiselectable", "true");
    list.hidden = true;

    root.append(chips, input, list);
    select.hidden = true;
    select.after(root);
    const label = document.querySelector(`label[for="${select.id}"]`);
    if (label) {
        label.htmlFor = input.id;
    }

    // --- state --------------------------------------------------------------
    let items = []; // {type: "option" | "new", option?, text}
    let active = -1;
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

    function close() {
        list.hidden = true;
        input.setAttribute("aria-expanded", "false");
        input.removeAttribute("aria-activedescendant");
        active = -1;
    }

    function setActive(index) {
        active = index;
        Array.from(list.children).forEach((li, i) => {
            li.classList.toggle("is-active", i === index);
            li.setAttribute("aria-selected", i === index ? "true" : "false");
        });
        if (index >= 0) {
            input.setAttribute("aria-activedescendant", list.children[index].id);
            list.children[index].scrollIntoView({ block: "nearest" });
        } else {
            input.removeAttribute("aria-activedescendant");
        }
    }

    function render() {
        const query = norm(input.value);
        items = options
            .filter((option) => !option.selected && option.value)
            .filter((option) => norm(option.textContent).includes(query))
            .map((option) => ({ type: "option", option, text: option.textContent }));

        const exact = options.some((option) => norm(option.textContent) === query);
        if (!hasNew() && !exact) {
            items.push({
                type: "new",
                text: query
                    ? `＋ Add new guidebook “${input.value.trim()}”…`
                    : "＋ Add new guidebook…",
            });
        }

        list.replaceChildren();
        items.forEach((item, i) => {
            const li = document.createElement("li");
            li.id = `guidebook-option-${i}`;
            li.setAttribute("role", "option");
            li.setAttribute("aria-selected", "false");
            li.className = item.type === "new" ? "is-add" : "";
            li.textContent = item.text;
            // mousedown, not click: fires before the input loses focus
            li.addEventListener("mousedown", (event) => {
                event.preventDefault();
                choose(item);
            });
            list.append(li);
        });
        if (!items.length) {
            const li = document.createElement("li");
            li.className = "is-empty";
            li.textContent = "No guidebooks found.";
            list.append(li);
        }
        list.hidden = false;
        input.setAttribute("aria-expanded", "true");
        setActive(items.length ? 0 : -1);
    }

    function choose(item) {
        if (item.type === "option") {
            item.option.selected = true;
            input.value = "";
            renderChips();
            close();
        } else {
            openDialog(input.value.trim());
        }
    }

    function openDialog(prefillName) {
        if (prefillName && !hasNew()) {
            nameInput.value = prefillName;
        }
        close();
        dialog.showModal();
        nameInput.focus();
    }

    // --- events -------------------------------------------------------------
    input.addEventListener("input", render);
    input.addEventListener("focus", render);
    input.addEventListener("blur", close);
    input.addEventListener("keydown", (event) => {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            if (list.hidden) {
                render();
                return;
            }
            const step = event.key === "ArrowDown" ? 1 : -1;
            setActive((active + step + items.length) % items.length);
        } else if (event.key === "Enter") {
            event.preventDefault(); // never submit the crag form from here
            if (!list.hidden && items[active]) {
                choose(items[active]);
            }
        } else if (event.key === "Escape") {
            close();
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
