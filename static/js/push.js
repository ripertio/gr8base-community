// Push notifications on this device (crags/push.py) and the number on the app icon.
//
// - Notification settings page ([data-push]): turn this device on or off.
// - Sign-out forms ([data-push-logout]): turn this device off first, so a shared
//   device stops getting the previous person's notifications.
// - Every page: keep the app icon number in sync with the counters (data-badge).
// Loaded only for logged-in users with push enabled (templates/base.html).
(function () {
  var script = document.currentScript;
  var supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

  // --- app icon number --------------------------------------------------------
  function setBadge(count) {
    if (!("setAppBadge" in navigator)) return;
    (count > 0 ? navigator.setAppBadge(count) : navigator.clearAppBadge()).catch(function () {});
  }
  if (script) setBadge(Number(script.dataset.badge || 0));

  // --- helpers ----------------------------------------------------------------
  function currentSubscription() {
    if (!supported) return Promise.resolve(null);
    return navigator.serviceWorker.getRegistration().then(function (registration) {
      return registration ? registration.pushManager.getSubscription() : null;
    });
  }

  function post(url, csrf, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(body),
      credentials: "same-origin",
      keepalive: true,
    });
  }

  // the public key comes base64url-encoded; the browser wants raw bytes
  function keyBytes(base64url) {
    var padded = base64url + "====".slice(0, (4 - (base64url.length % 4)) % 4);
    var raw = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
    var bytes = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    return bytes;
  }

  // --- settings page: this device on/off ----------------------------------------
  var box = document.querySelector("[data-push]");
  if (box) {
    var status = box.querySelector("[data-push-status]");
    var turnOn = box.querySelector("[data-push-on]");
    var turnOff = box.querySelector("[data-push-off]");

    var show = function (text, state) {
      status.textContent = text;
      turnOn.hidden = state !== "off";
      turnOff.hidden = state !== "on";
    };

    var refresh = function () {
      if (!supported) {
        var apple = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
          (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
        var installed = navigator.standalone || window.matchMedia("(display-mode: standalone)").matches;
        show(apple && !installed
          ? "On iPhone and iPad: tap Share → Add to Home Screen, open gr8base from your home screen and turn notifications on there."
          : "This browser does not support push notifications.", "none");
        return Promise.resolve();
      }
      if (Notification.permission === "denied") {
        show("Notifications are blocked for this site. Allow them in your browser or phone settings, then reload this page.", "none");
        return Promise.resolve();
      }
      return currentSubscription().then(function (subscription) {
        show(subscription ? "On for this device." : "Off for this device.", subscription ? "on" : "off");
      });
    };

    turnOn.addEventListener("click", function () {
      show("Turning on…", "none");
      navigator.serviceWorker.register(box.dataset.workerUrl)
        .then(function () { return navigator.serviceWorker.ready; })
        .then(function (registration) {
          return Notification.requestPermission().then(function (permission) {
            if (permission !== "granted") throw new Error("permission");
            return registration.pushManager.subscribe({
              userVisibleOnly: true,
              applicationServerKey: keyBytes(box.dataset.publicKey),
            });
          });
        })
        .then(function (subscription) {
          return post(box.dataset.subscribeUrl, box.dataset.csrf, subscription.toJSON())
            .then(function (response) {
              if (!response.ok) throw new Error("server");
              return response.json();
            });
        })
        .then(function (data) { setBadge(data.badge); return refresh(); })
        .catch(function (error) {
          refresh().then(function () {
            if (error.message !== "permission") {
              status.textContent = "Could not turn on notifications on this device. Please try again.";
            }
          });
        });
    });

    turnOff.addEventListener("click", function () {
      show("Turning off…", "none");
      currentSubscription()
        .then(function (subscription) {
          if (!subscription) return;
          return post(box.dataset.unsubscribeUrl, box.dataset.csrf, { endpoint: subscription.endpoint })
            .then(function () { return subscription.unsubscribe(); });
        })
        .catch(function () {})
        .then(function () { setBadge(0); return refresh(); });
    });

    refresh();
  }

  // --- signing out: turn this device off first --------------------------------
  document.querySelectorAll("form[data-push-logout]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var csrf = form.querySelector("[name=csrfmiddlewaretoken]").value;
      var finished = false;
      var finish = function () {
        if (finished) return;
        finished = true;
        setBadge(0);
        form.submit(); // does not fire "submit" again
      };
      var timer = setTimeout(finish, 1500); // never block signing out
      currentSubscription()
        .then(function (subscription) {
          if (!subscription) return;
          return post(form.dataset.unsubscribeUrl, csrf, { endpoint: subscription.endpoint })
            .then(function () { return subscription.unsubscribe(); });
        })
        .catch(function () {})
        .then(function () { clearTimeout(timer); finish(); });
    });
  });
})();
