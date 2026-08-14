// brasenia Cast receiver — Phase A (issue #13, ADR-0006).
//
// Phase A behavior only: point at a fixed target and never leave the screen
// blank. Phase B swaps TARGET_URL for the compositor's current-pane pointer
// and re-navigates on change (docs/concept.md) — out of scope here.
(function () {
  var TARGET_URL = 'http://pub.lan/brief/';
  var LOAD_TIMEOUT_MS = 8000;
  var RETRY_INTERVAL_MS = 15000;

  var frame = document.getElementById('pane');
  var statusCard = document.getElementById('status-card');
  var statusMessage = statusCard.querySelector('.message');
  var loadTimer = null;
  var retryTimer = null;

  function showPane() {
    clearTimeout(retryTimer);
    statusCard.hidden = true;
    frame.hidden = false;
  }

  // Mirrors the compositor's fallback ladder (docs/concept.md): the screen
  // must show something, never go blank, while the target is unreachable.
  function showStatusCard(message) {
    frame.hidden = true;
    statusCard.hidden = false;
    statusMessage.textContent = message;
    clearTimeout(retryTimer);
    retryTimer = setTimeout(loadPane, RETRY_INTERVAL_MS);
  }

  function loadPane() {
    clearTimeout(loadTimer);
    // The iframe's error event only fires reliably for network-level
    // failures (DNS, connection refused), not HTTP error statuses, so the
    // load timeout is the primary unreachable signal.
    loadTimer = setTimeout(function () {
      showStatusCard('brief unreachable — retrying…');
    }, LOAD_TIMEOUT_MS);

    var bust = (TARGET_URL.indexOf('?') === -1 ? '?' : '&') + 'r=' + Date.now();
    frame.src = TARGET_URL + bust;
  }

  frame.addEventListener('load', function () {
    clearTimeout(loadTimer);
    showPane();
  });

  frame.addEventListener('error', function () {
    clearTimeout(loadTimer);
    showStatusCard('brief unreachable — retrying…');
  });

  loadPane();

  // Signage app, no media session — the default CAF idle timeout would
  // otherwise terminate the receiver after a few minutes with zero senders
  // connected. disableIdleTimeout keeps it running unattended.
  var context = cast.framework.CastReceiverContext.getInstance();
  context.start({ disableIdleTimeout: true });
})();
