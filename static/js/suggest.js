// Suggestion list (combobox) for a text input: the one implementation used by
// the guidebook picker, the area picker and the crag search.
// Exposes window.gr8Suggest(input, options), window.gr8Normalize(text) and
// window.gr8Match(entries, nameOf, query, limit).
//
//   source(query)  -> [{text, hint?, className?, ...}]  items to show
//   onChoose(item) -> called when an item is clicked or picked with Enter
//   showEmpty      -> also show suggestions for an empty input (on focus)
//   emptyText      -> text when nothing matches ("" = hide the list instead)
//   autoActivate   -> highlight the first item, so Enter picks it
//   multiple       -> the field selects several values (aria-multiselectable)
//
// Enter without a highlighted item is left to the page (e.g. submit a search).
// Call this after the input is in the document: it wraps the input in
// <div class="suggest"> and puts the list next to it.
(() => {
    let counter = 0;

    // "Allgäu" matches "allgau": lower case, no accents, single spaces
    window.gr8Normalize = (text) =>
        (text || "")
            .normalize("NFD")
            .replace(/[̀-ͯ]/g, "")
            .trim()
            .replace(/\s+/g, " ")
            .toLowerCase();

    // 0: starts with the query, 1: a word starts with it, 2: contains it, -1: no match
    function rank(name, query) {
        if (name.startsWith(query)) return 0;
        if (name.includes(` ${query}`) || name.includes(`-${query}`)) return 1;
        if (name.includes(query)) return 2;
        return -1;
    }

    // Entries whose name matches the query, best matches first, then by name.
    // An empty query keeps every entry in its original order.
    window.gr8Match = (entries, nameOf, text, limit = Infinity) => {
        const query = gr8Normalize(text);
        if (!query) {
            return entries.slice(0, limit);
        }
        return entries
            .map((entry) => ({ entry, score: rank(gr8Normalize(nameOf(entry)), query) }))
            .filter(({ score }) => score >= 0)
            .sort((a, b) => a.score - b.score || nameOf(a.entry).localeCompare(nameOf(b.entry)))
            .slice(0, limit)
            .map(({ entry }) => entry);
    };

    window.gr8Suggest = (input, options) => {
        const {
            source,
            onChoose,
            showEmpty = false,
            emptyText = "",
            autoActivate = false,
            multiple = false,
        } = options;
        const id = `suggest-${++counter}`;

        const wrapper = document.createElement("div");
        wrapper.className = "suggest";
        input.before(wrapper);
        wrapper.append(input);

        const list = document.createElement("ul");
        list.id = id;
        list.className = "suggestions";
        list.setAttribute("role", "listbox");
        if (multiple) {
            list.setAttribute("aria-multiselectable", "true");
        }
        list.hidden = true;
        wrapper.append(list);

        input.autocomplete = "off";
        input.setAttribute("role", "combobox");
        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-expanded", "false");
        input.setAttribute("aria-controls", id);

        let items = [];
        let active = -1;

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
            const query = input.value;
            if (!showEmpty && !gr8Normalize(query)) {
                close();
                return;
            }
            items = source(query);
            list.replaceChildren();
            items.forEach((item, i) => {
                const li = document.createElement("li");
                li.id = `${id}-${i}`;
                li.setAttribute("role", "option");
                li.setAttribute("aria-selected", "false");
                if (item.className) {
                    li.className = item.className;
                }
                const name = document.createElement("span");
                name.textContent = item.text;
                li.append(name);
                if (item.hint) {
                    const hint = document.createElement("small");
                    hint.textContent = item.hint;
                    li.append(hint);
                }
                // mousedown, not click: fires before the input loses focus
                li.addEventListener("mousedown", (event) => {
                    event.preventDefault();
                    choose(item);
                });
                list.append(li);
            });
            if (!items.length) {
                if (!emptyText) {
                    close();
                    return;
                }
                const li = document.createElement("li");
                li.className = "is-empty";
                li.textContent = emptyText;
                list.append(li);
            }
            list.hidden = false;
            input.setAttribute("aria-expanded", "true");
            setActive(autoActivate && items.length ? 0 : -1);
        }

        function choose(item) {
            close();
            onChoose(item);
        }

        input.addEventListener("input", render);
        input.addEventListener("focus", () => {
            if (showEmpty || gr8Normalize(input.value)) {
                render();
            }
        });
        input.addEventListener("blur", close);
        input.addEventListener("keydown", (event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                if (list.hidden) {
                    render();
                    return;
                }
                if (!items.length) {
                    return;
                }
                const step = event.key === "ArrowDown" ? 1 : -1;
                const start = active === -1 && step === -1 ? items.length : active;
                setActive((start + step + items.length) % items.length);
            } else if (event.key === "Enter") {
                if (!list.hidden && items[active]) {
                    event.preventDefault();
                    choose(items[active]);
                }
            } else if (event.key === "Escape") {
                if (!list.hidden) {
                    event.preventDefault(); // keep the text (search inputs clear on Escape)
                    close();
                }
            }
        });

        return { close, render };
    };
})();
