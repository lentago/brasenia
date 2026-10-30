"""The pane page that frames a rendered dashboard.

One 1920×1080 band (the pane contract's canvas, ADR-0019). The dashboard sits
in FRAME, the 1848×915 box inside the 36 px margins, scaled to fit and centred.
The footer sits bottom-left at y=1005..1044 and stops 534 px short of the right
edge, so the bottom-right clock corner stays empty. The PNG is inlined as a data: URI,
so the page is self-contained and its content revision (ADR-0016, a hash of
pane.html) moves with every good render: the footer's "as of" time is in it. Grafana's
own footer is in the ``crop_px`` strip rendered below the dashboard, which the frame cuts off.
"""

import base64
import html

FRAME_W, FRAME_H, MARGIN = 1848, 915, 36
BG, TEXT, FAINT = "#0f1518", "#e4ebee", "#73858e"


def fit(size, crop_px):
    """``(left, width, height, image height)`` in CSS px of a ``size`` dashboard in FRAME."""
    width, height = size
    k = min(FRAME_W / width, FRAME_H / height)
    shown_w, shown_h = round(width * k), round(height * k)
    return (MARGIN + (FRAME_W - shown_w) // 2, shown_w, shown_h,
            round((height + crop_px) * k))


def clock(dt, tz):
    return dt.astimezone(tz).strftime("%-I:%M %p")


def page(slot, png, rendered_at, tz):
    """The whole pane page for ``slot``'s dashboard ``png``, rendered at ``rendered_at``."""
    left, width, height, image_h = fit(slot.size, slot.crop_px)
    e = html.escape
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="brasenia-canvas" content="1920x1080">
<title>%(title)s</title>
<style>
html, body { margin: 0; padding: 0; }
body { width: 1920px; height: 1080px; overflow: hidden; position: relative;
  background: %(bg)s; color: %(text)s; font-family: "DejaVu Sans", sans-serif; }
.frame { position: absolute; left: %(left)dpx; top: %(margin)dpx; width: %(width)dpx;
  height: %(height)dpx; overflow: hidden; border-radius: 9px; }
.frame img { display: block; width: %(width)dpx; height: %(image_h)dpx; }
.foot { position: absolute; left: %(margin)dpx; bottom: %(margin)dpx; width: 1350px; height: 39px;
  font-size: 30px; line-height: 39px; color: %(faint)s; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
</style></head>
<body>
<div class="frame"><img alt="%(title)s" src="data:image/png;base64,%(png)s"></div>
<div class="foot">%(title)s · Grafana · as of %(when)s</div>
</body></html>
""" % {"title": e(slot.title), "bg": BG, "text": TEXT, "faint": FAINT, "margin": MARGIN,
       "left": left, "width": width, "height": height, "image_h": image_h,
       "png": base64.b64encode(png).decode("ascii"), "when": e(clock(rendered_at, tz))}
