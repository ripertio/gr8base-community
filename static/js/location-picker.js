(() => {
    const button = document.querySelector("[data-use-current-location]");
    const status = document.querySelector("[data-location-status]");
    if (!button || !status) {
        return;
    }

    button.addEventListener("click", () => {
        if (!navigator.geolocation) {
            status.textContent = "Location services are not supported by this browser.";
            return;
        }

        button.disabled = true;
        status.textContent = "Getting your location…";

        navigator.geolocation.getCurrentPosition(
            (position) => {
                const location = document.querySelector('[name="location"]');
                if (!location) {
                    button.disabled = false;
                    status.textContent = "The location field could not be found.";
                    return;
                }

                location.value = `${position.coords.latitude.toFixed(6)}, ${position.coords.longitude.toFixed(6)}`;
                location.dispatchEvent(new Event("input", { bubbles: true }));
                location.dispatchEvent(new Event("change", { bubbles: true }));
                button.disabled = false;
                status.textContent = "Location added.";
            },
            (error) => {
                button.disabled = false;
                if (error.code === error.PERMISSION_DENIED) {
                    status.textContent = "Location access was denied.";
                } else if (error.code === error.POSITION_UNAVAILABLE) {
                    status.textContent = "Your location is currently unavailable.";
                } else if (error.code === error.TIMEOUT) {
                    status.textContent = "Location detection timed out.";
                } else {
                    status.textContent = "Could not determine your location.";
                }
            },
            { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
        );
    });
})();
