// Suggestions for the crag list search: matching areas and crags while typing.
// Picking a crag opens it; picking an area filters the list by that area.
// While the list is filtered by an area, only crags in that area are suggested.
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
    const areaSelect = form.querySelector('select[name="area"]');

    const MAX_AREAS = 3;
    const MAX_TOTAL = 8;

    function source(text) {
        // With an area filter active, stay inside that area: only its crags and
        // no other areas (changing the area is the filter dropdown's job).
        const filterArea = areaSelect ? areaSelect.value : "";
        const areaItems = areaSelect && !filterArea
            ? gr8Match(areas, (name) => name, text, MAX_AREAS).map((name) => ({
                  type: "area",
                  text: name,
                  hint: "Area",
              }))
            : [];
        const candidates = filterArea ? crags.filter((crag) => crag.area === filterArea) : crags;
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
            areaSelect.value = item.text;
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
