// brasenia Cast receiver — Phase B (issue #13, ADR-0006).
//
// Follows the compositor's current-pane pointer (current.json, schema 1):
// polls it, navigates the iframe only when `url` changes, and never leaves
// the screen blank. A 404 on the pointer means the compositor doesn't exist
// yet, so behave exactly as Phase A and load the brief.
(function () {
  var POINTER_URL = 'http://pub.lan/viewport/current.json';
  var BRIEF_URL = 'http://pub.lan/brief/';
  var POLL_INTERVAL_MS = 5000;
  var POINTER_FETCH_TIMEOUT_MS = 4000;
  var POINTER_STALE_MS = 30000;
  var LOAD_TIMEOUT_MS = 8000;

  var frame = document.getElementById('pane');
  var statusCard = document.getElementById('status-card');
  var statusMessage = statusCard.querySelector('.message');
  var loadTimer = null;

  var currentUrl = null;       // last URL navigated to; null forces a reload
  var currentIsBrief = false;  // wording for the status card only
  var unreadableSince = null;  // when the pointer first became unreadable
  var pointerDown = false;     // unreadable for >= POINTER_STALE_MS
  var paneFailed = false;      // pane URL did not load within LOAD_TIMEOUT_MS

  // The screen must show something, never go blank: the status card covers
  // either failure, and the last pane stays up until a failure is confirmed.
  function render() {
    var message = null;
    if (pointerDown) {
      message = 'viewport pointer unreachable — retrying…';
    } else if (paneFailed) {
      message = (currentIsBrief ? 'brief' : 'pane') + ' unreachable — retrying…';
    }
    statusCard.hidden = message === null;
    frame.hidden = message !== null;
    if (message !== null) {
      statusMessage.textContent = message;
    }
  }

  function navigate(url, isBrief) {
    clearTimeout(loadTimer);
    currentUrl = url;
    currentIsBrief = isBrief;
    // The iframe's error event only fires reliably for network-level
    // failures (DNS, connection refused), not HTTP error statuses, so the
    // load timeout is the primary unreachable signal. On failure, clear
    // currentUrl so the next poll re-navigates to the same URL; the
    // compositor, not this receiver, decides any fallback.
    loadTimer = setTimeout(paneLoadFailed, LOAD_TIMEOUT_MS);
    frame.src = url + (url.indexOf('?') === -1 ? '?' : '&') + 'r=' + Date.now();
  }

  function paneLoadFailed() {
    clearTimeout(loadTimer);
    currentUrl = null;
    paneFailed = true;
    render();
  }

  frame.addEventListener('load', function () {
    clearTimeout(loadTimer);
    paneFailed = false;
    render();
  });

  frame.addEventListener('error', paneLoadFailed);

  function pointerReadable() {
    unreadableSince = null;
    pointerDown = false;
  }

  function pointerUnreadable() {
    var now = Date.now();
    if (unreadableSince === null) {
      unreadableSince = now;
    }
    if (now - unreadableSince >= POINTER_STALE_MS) {
      pointerDown = true;
    }
    render();
  }

  function applyPointer(pointer) {
    if (!pointer || pointer.schema !== 1 || typeof pointer.url !== 'string' || !pointer.url) {
      pointerUnreadable();
      return;
    }
    pointerReadable();
    if (pointer.url !== currentUrl) {
      navigate(pointer.url, false);
    }
    render();
  }

  function poll() {
    var done = false;
    var controller = typeof AbortController === 'function' ? new AbortController() : null;
    var abortTimer = setTimeout(function () {
      if (controller) controller.abort();
    }, POINTER_FETCH_TIMEOUT_MS);

    function finish(fn) {
      if (done) return;
      done = true;
      clearTimeout(abortTimer);
      fn();
      setTimeout(poll, POLL_INTERVAL_MS);
    }

    fetch(POINTER_URL, { cache: 'no-store', signal: controller ? controller.signal : undefined })
      .then(function (res) {
        if (res.status === 404) {
          // No compositor yet: Phase A behaviour.
          return finish(function () {
            pointerReadable();
            if (currentUrl !== BRIEF_URL) {
              navigate(BRIEF_URL, true);
            }
            render();
          });
        }
        if (!res.ok) {
          return finish(pointerUnreadable);
        }
        return res.json().then(
          function (pointer) { finish(function () { applyPointer(pointer); }); },
          function () { finish(pointerUnreadable); }
        );
      })
      .catch(function () { finish(pointerUnreadable); });
  }

  poll();

  // Signage app, no media session — the default CAF idle timeout would
  // otherwise terminate the receiver after a few minutes with zero senders
  // connected. disableIdleTimeout keeps it running unattended.
  var context = cast.framework.CastReceiverContext.getInstance();
  context.start({ disableIdleTimeout: true });
})();
