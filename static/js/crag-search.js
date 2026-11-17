// Suggestions for the crag list search: matching areas and crags while typing.
// Picking a crag opens it; picking an area filters the list by that area.
// While the list is filtered by areas, only crags in those areas are suggested.
// Enter without picking a suggestion still runs the normal full-text search.
//
// The names come from data-crag-search (a JSON URL), loaded the first time the
// field is used, so the list page itself stays small. Without the data (offline,
// error) the field is a plain search field.
(() => {
    const input = document.querySelector("[data-crag-search]");
    if (!input || !input.dataset.cragSearch || !window.gr8Suggest || !window.fetch) {
        return;
    }
    let crags = [];
    let areas = [];
    let loading = null;
    const form = input.form;
    const areaBoxes = Array.from(form.querySelectorAll('input[name="area"]'));

    const MAX_AREAS = 3;
    const MAX_TOTAL = 8;

    function source(text) {
        // With an area filter active, stay inside those areas: only their crags
        // and no area suggestions (changing areas is the filter panel's job).
        const filterAreas = new Set(areaBoxes.filter((box) => box.checked).map((box) => box.value));
        const areaItems = areaBoxes.length && !filterAreas.size
            ? gr8Match(areas, (name) => name, text, MAX_AREAS).map((name) => ({
                  type: "area",
                  text: name,
                  hint: "Area",
              }))
            : [];
        const candidates = filterAreas.size ? crags.filter((crag) => filterAreas.has(crag.area)) : crags;
        const cragItems = gr8Match(candidates, (crag) => crag.name, text, MAX_TOTAL - areaItems.length).map(
            (crag) => ({ type: "crag", text: crag.name, hint: crag.area, url: crag.url })
        );
        return [...areaItems, ...cragItems];
    }

    const suggest = gr8Suggest(input, {
        source,
        onChoose(item) {
            if (item.type === "crag") {
                window.location.href = item.url;
                return;
            }
            // only offered while no area is ticked: tick just this one
            const box = areaBoxes.find((candidate) => candidate.value === item.text);
            if (!box) {
                return;
            }
            box.checked = true;
            input.value = "";
            form.submit();
        },
    });

    function load() {
        if (loading) {
            return;
        }
        loading = fetch(input.dataset.cragSearch, { headers: { Accept: "application/json" } })
            .then((response) => (response.ok ? response.json() : Promise.reject(response.status)))
            .then((data) => {
                crags = data.crags || [];
                areas = data.areas || [];
                if (document.activeElement === input) {
                    suggest.render(); // show what was typed while loading
                }
            })
            .catch(() => {
                loading = null; // try again on the next focus
            });
    }

    input.addEventListener("focus", load);
    input.addEventListener("input", load);
})();
