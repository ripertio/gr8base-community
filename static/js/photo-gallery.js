(() => {
    const dialog = document.querySelector(".photo-gallery");
    if (!dialog || typeof dialog.showModal !== "function") {
        return;
    }

    const links = Array.from(document.querySelectorAll("[data-gallery-image]"));
    if (!links.length) {
        return;
    }

    const image = dialog.querySelector("[data-gallery-view]");
    const caption = dialog.querySelector("[data-gallery-caption]");
    const counter = dialog.querySelector("[data-gallery-counter]");
    let currentIndex = 0;
    let pointerStartX = null;

    const showPhoto = (index) => {
        currentIndex = (index + links.length) % links.length;
        const link = links[currentIndex];
        image.src = link.href;
        image.alt = link.dataset.alt || "";
        caption.textContent = link.dataset.caption || image.alt;
        counter.textContent = `${currentIndex + 1} von ${links.length}`;
    };

    links.forEach((link, index) => {
        link.addEventListener("click", (event) => {
            event.preventDefault();
            showPhoto(index);
            dialog.showModal();
            dialog.querySelector("[data-gallery-close]").focus();
        });
    });

    dialog.querySelector("[data-gallery-close]").addEventListener("click", () => {
        dialog.close();
    });
    dialog.querySelector("[data-gallery-previous]").addEventListener("click", () => {
        showPhoto(currentIndex - 1);
    });
    dialog.querySelector("[data-gallery-next]").addEventListener("click", () => {
        showPhoto(currentIndex + 1);
    });

    dialog.addEventListener("click", (event) => {
        if (event.target === dialog) {
            dialog.close();
        }
    });

    dialog.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            event.preventDefault();
            dialog.close();
        } else if (event.key === "ArrowLeft") {
            event.preventDefault();
            showPhoto(currentIndex - 1);
        } else if (event.key === "ArrowRight") {
            event.preventDefault();
            showPhoto(currentIndex + 1);
        }
    });

    image.addEventListener("pointerdown", (event) => {
        pointerStartX = event.clientX;
    });
    image.addEventListener("pointerup", (event) => {
        if (pointerStartX === null) {
            return;
        }
        const distance = event.clientX - pointerStartX;
        pointerStartX = null;
        if (Math.abs(distance) >= 50) {
            showPhoto(currentIndex + (distance < 0 ? 1 : -1));
        }
    });
    image.addEventListener("pointercancel", () => {
        pointerStartX = null;
    });
})();
