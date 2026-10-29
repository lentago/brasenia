# ADR-0017: Grafana dashboards are rendered on pub into ordinary panes

**Status:** Accepted (2026-10-29; #98). Amends
[ADR-0014](0014-home-and-fleet-feed-resting-panes.md): a second producer on
pub holds a credential.

## Context

The household wants Grafana Cloud dashboards on the wall. Grafana Cloud needs
a login: on LXC 118, a dashboard URL renders the login page (14.6 s,
2026-10-29). Anonymous access and panel embedding are not available in
Grafana Cloud at all [1]. So a dashboard cannot be a link pane
([ADR-0016](0016-panes-carry-a-revision-and-may-link-a-web-page.md)):
the renderer would need a credential, and LXC 118 is credential-free by
design. ADR-0016 already decided that pages needing a login are rendered on
pub into ordinary panes. The stack's render API does return a dark 1280×720
PNG of a dashboard; this was tested on "On-prem — Infrastructure Health".

#98 left three questions open: the render API's rate limits and so the
refresh cadence, where the service account is defined, and what to do about
Grafana's "Powered by" footer, which sits in the clock's corner.

## Decision

- **A producer on pub renders each dashboard slot into a pane**
  ([`producers/grafana/`](../../producers/grafana/)). Each slot names a
  dashboard UID, a layout size, a theme and a refresh cadence. The pane holds
  `dashboard.png` and a `pane.html` that frames it, with the PNG inlined as a
  `data:` URI. The page is then self-contained as the pane contract asks, and
  its `rev` (a hash of `pane.html`) moves exactly when the image does.
  `dashboard.png` is a rendition beside it, which the compositor ignores. The
  panes are `ambient`, so they join the resting rung beside Home, Weather and
  Fleet.

- **The token is a Viewer service-account token, held by pub alone.** It is a
  systemd credential of `brasenia-grafana.service`
  (`LoadCredential=grafana-token:/etc/brasenia/grafana-token`, a root-only
  file), as the Home Assistant token is. It is never in git, on the share, in
  a URL, in a log or on a page. A Viewer can read dashboards and nothing else,
  which is all the render API needs.

- **The service account is defined in drosera**, which owns the Grafana Cloud
  stack as code and applies it on merge
  ([drosera#287](https://github.com/lentago/drosera/issues/287)).
  It is not created by hand in the stack. Its token is minted by hand under
  that account and placed on pub, rather than by Terraform
  (`grafana_service_account_token`), whose key would then sit in drosera's
  remote state, a bucket in a shared AWS account. The unit and the slot file
  are kalmia's
  ([kalmia#202](https://github.com/lentago/kalmia/issues/202)).

- **Each slot renders every 300 s by default, never more often than every
  60 s, and renders run one at a time.** A failure waits `refresh_s`, then
  doubles up to an hour, and never less than a 429's `Retry-After`. A pane's
  TTL covers three refreshes (at least 10 minutes), so a failed render or two
  keep the last image, stamped "as of" its time, and a dead token takes the
  pane off the bus.

  Grafana publishes no requests-per-minute limit for the render API, in
  Grafana Cloud or elsewhere. What it documents is concurrency and cost:

  - Grafana caps concurrent `/render` requests with
    `concurrent_render_request_limit`, default 30, "by only allowing a certain
    number of concurrent requests" [2].
  - The image renderer rate-limits by memory and running requests: it
    "will reject requests if the number of currently running requests is at
    or above" its limit, and never rejects below `rate-limit.min-limit`,
    default 3 [3].
  - Each render is a headless Chromium page load that waits up to 30 s for the
    page to be ready [3]; Grafana asks for at least 16 GiB and 4 cores for a
    renderer, because "some rendering tasks require several gigabytes of
    memory and many cores in a spiky pattern" [4]. Each render also runs every
    panel's queries, as a person opening the dashboard would.
  - In Grafana Cloud, the renderer's configuration "is managed by Grafana and
    can't be modified" [1], and other settings change only by support ticket
    [2]. The stack's usage limits list none for rendering [5].

  So the limit that matters is concurrency on a shared, Grafana-managed
  renderer, and the courtesy owed is to keep renders few and never parallel.
  One render at a time stays under the renderer's floor of 3 whatever else
  the stack is doing. Every 300 s is 288 renders a slot a day, against
  dashboards whose data is scraped every minute, on a pane that rests on the
  wall; anything urgent is a different pane. A slot that truly needs fresher
  data can go to 60 s.

- **The "Powered by" footer is cropped.** Each render asks for `crop_px`
  (default 40) more height than the slot's size, and the pane's frame cuts it
  off. The frame sits inside the 24 px margins and ends above the clock's
  band, and the pane's own footer, bottom-left, names Grafana as the source
  and the time of the render. The clock is composited over the bottom-right
  corner. Left in place, the footer would show around the clock's edges, and
  the pane contract keeps that corner clear on pages we write. Cropping is
  free: it is a few pixels of height in the request, and nothing is edited in
  the image. 40 px is an estimate. The first render on pub checks it, and a
  slot raises `crop_px` if the footer still shows.

## Consequences

- **Two producers on pub now hold a credential.** Both tokens are systemd
  credentials of one unit each, from root-only files, seeded by hand. Neither
  reaches LXC 118, the share or a client.
- **A dashboard on the wall is at most `refresh_s` plus a render old**, and
  its footer says when it was rendered.
- **A Viewer token can read every dashboard in the stack**, not only the
  slots. drosera keeps every dashboard in one `Lentago` folder (its ADR-0007),
  so a narrower grant would gain little; the token stays on pub.
- **Grafana layout is Grafana's.** A dashboard laid out for a desk screen may
  be small on the wall. A slot's `size` sets the layout size, and the pane
  scales it to fit, so a dashboard can be laid out at 1920 wide and shown at
  1232.
- **Rendering depends on the internet.** When Grafana Cloud is unreachable,
  the panes go stale and then leave the bus; the rest of the wall is
  unaffected.

## Alternatives considered

- **Link panes with a credential on LXC 118.** Rejected by ADR-0016 and
  ADR-0005: the display guest holds no secret.
- **A public (externally shared) dashboard as a link pane.** No credential,
  but it publishes our infrastructure dashboards to the internet, and it is
  still an outside page for a renderer that is not yet sandboxed
  (kalmia#194).
- **Accept the footer.** It costs nothing to remove, and it would sit under
  the clock.
- **Crop in the image.** Cutting pixels needs an image library, which the
  producers avoid (stdlib only); the request and the frame do it.
- **A token minted by Terraform.** One fewer manual step, but the key lands in
  remote state, where anyone who can read the state can read it, and rotating
  it means a replace. Seeding by hand is how every pub credential works.
- **A faster cadence (60 s).** Five times the renders for a resting pane,
  with no documented headroom to point to. Kept as the minimum a slot may
  ask for.

## References

1. Grafana, "Share dashboards and panels": anonymous access and panel
   embedding are not available in Grafana Cloud; render query parameters; "The
   image renderer enforces minimum dimensions of 1000px for width and 500px
   for height … In Grafana Cloud, the configuration is managed by Grafana and
   can't be modified."
   <https://grafana.com/docs/grafana/latest/visualizations/dashboards/share-dashboards-panels/>
2. Grafana, "Configure Grafana": `[rendering] concurrent_render_request_limit`
   (default 30), and "There is no local configuration file for Grafana Cloud
   stacks … To edit configurable settings, open a support ticket."
   <https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/>
3. Grafana, "Image renderer flags": `rate-limit.max-limit`,
   `rate-limit.min-limit` (default 3), `browser.readiness.timeout` (default
   30 s), `browser.max-width` and `browser.max-height` (default 3000).
   <https://grafana.com/docs/grafana/latest/setup-grafana/image-rendering/flags/>
4. Grafana, "Set up image rendering": image rendering works with Grafana
   Cloud; resource needs of the renderer.
   <https://grafana.com/docs/grafana/latest/setup-grafana/image-rendering/>
5. Grafana Cloud, "Usage limits" (metrics, logs, traces, dashboards,
   annotations; nothing on rendering).
   <https://grafana.com/docs/grafana-cloud/cost-management-and-billing/understand-your-invoice/usage-limits/>

All retrieved 2026-10-29.
