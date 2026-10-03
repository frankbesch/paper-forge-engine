"""Quoin README charts: phone-first SVG primitives for GitHub READMEs.

Source: the Quoin design system's README module. Each repo carries a copy
written by the system's sync script; edit the source, then sync.

The canvas is 360 units wide, the width of a phone column, so text keeps
its size when GitHub fits the image to a phone. The smallest text is 12
units, 3.3% of the width. For the desktop the README places two pictures
inline in one paragraph: they sit side by side there and stack on a phone.
The two pictures of a pair share one height (D-262): each chart takes a
spread (0 to 1) that opens its spacing and a height to pad to, and pair()
grows the shorter one to its partner. Every figure comes from the caller;
this module holds no data.

Type (D-273): labels and figures are IBM Plex Mono, titles and notes IBM Plex
Sans. svg() embeds a woff2 subset of each face and weight the chart uses, so
GitHub shows the same type on every device; text is wrapped on real glyph
widths. Without fontTools or the font files it falls back to system fonts,
and check-readme reports the missing embed. Text wears ink or ink2 only;
colour goes on marks, outlines, and swatches (Quoin spec, chart rules).
"""
import base64
import glob
import io
import os
import re
import sys
import textwrap
from html import escape, unescape

W = 360
M, R = 16, 344  # left and right text margins
CH = 0.6        # width of one monospace character, as a share of the font size (Plex Mono: 600/1000)
MONO = 'ui-monospace, "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace'
SANS = '-apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif'
FACES = {"mono": "QuoinMono", "sans": "QuoinSans"}
FONT_FILES = {("mono", 400): "IBMPlexMono-Regular.otf", ("mono", 600): "IBMPlexMono-SemiBold.otf",
              ("sans", 400): "IBMPlexSans-Regular.otf", ("sans", 600): "IBMPlexSans-SemiBold.otf"}
FONT_DIRS = [os.environ.get("QUOIN_FONTS", ""), os.path.expanduser("~/Library/Fonts"), "/Library/Fonts"]


def _fonttools():
    """fontTools, or None. Homebrew installs it beside its own python."""
    try:
        import fontTools  # noqa: F401
    except ImportError:
        for p in glob.glob("/opt/homebrew/opt/fonttools/libexec/lib/python*/site-packages"):
            sys.path.append(p)
        try:
            import fontTools  # noqa: F401
        except ImportError:
            return None
    import logging
    from fontTools import subset, ttLib
    logging.getLogger("fontTools.subset").setLevel(logging.ERROR)  # "meta NOT subset" is expected
    return subset, ttLib


_FONTS = {}


def _font(family, weight):
    """(path, TTFont) for a face, cached; None when fontTools or the file is missing."""
    key = (family, 600 if weight and int(weight) >= 600 else 400)
    if key not in _FONTS:
        ft, found = _fonttools(), None
        if ft:
            for d in FONT_DIRS:
                p = os.path.join(d, FONT_FILES[key]) if d else ""
                if p and os.path.exists(p):
                    found = (p, ft[1].TTFont(p))
                    break
        _FONTS[key] = found
    return _FONTS[key]


def measure(s, size, family="mono", weight=None):
    """Width of a string in canvas units."""
    f = _font(family, weight)
    if family == "mono" or not f:
        return len(s) * size * (CH if family == "mono" else 0.56)
    font = f[1]
    cmap, hmtx, upm = font.getBestCmap(), font["hmtx"], font["head"].unitsPerEm
    default = hmtx[".notdef"][0] if ".notdef" in hmtx.metrics else upm // 2
    return sum(hmtx[cmap[ord(ch)]][0] if ord(ch) in cmap else default for ch in s) * size / upm


def embed(body):
    """<style> with a woff2 subset of each face and weight the text elements use."""
    ft = _fonttools()
    if not ft:
        return ""
    used = {}
    for attrs, inner in re.findall(r"<text\b([^>]*)>(.*?)</text>", body, re.S):
        family = "sans" if FACES["sans"] in attrs else "mono"
        w = re.search(r'font-weight="(\d+)"', attrs)
        key = (family, 600 if w and int(w.group(1)) >= 600 else 400)
        used.setdefault(key, set()).update(unescape(re.sub(r"<[^>]+>", "", inner)))
    rules = []
    for (family, weight), chars in sorted(used.items()):
        f = _font(family, weight)
        if not f:
            return ""
        opts = ft[0].Options()
        opts.flavor, opts.hinting, opts.layout_features = "woff2", False, ["kern"]
        opts.name_IDs, opts.notdef_outline = [1, 2], True
        font = ft[1].TTFont(f[0], recalcTimestamp=False)  # same bytes on every rebuild
        sub = ft[0].Subsetter(opts)
        sub.populate(text="".join(sorted(chars)))
        sub.subset(font)
        buf = io.BytesIO()
        font.flavor = "woff2"
        font.save(buf)
        data = base64.b64encode(buf.getvalue()).decode()
        rules.append(f'@font-face{{font-family:"{FACES[family]}";font-weight:{weight};'
                     f'src:url(data:font/woff2;base64,{data}) format("woff2")}}')
    return "<style>" + "".join(rules) + "</style>\n" if rules else ""

# Quoin tokens (chrome) and Quoin chart palette (data marks); quoin/tokens.json.
THEMES = {
    "light": dict(paper="#FCFBF9", ink="#2B2926", ink2="#6A625A", rule="#D2CCC3", tint="#EBE6DD",
                  series=["#33703F", "#0084A9", "#916A0B", "#90302B", "#23749E"]),
    "dark": dict(paper="#0E1C2B", ink="#E8E2D6", ink2="#A8A296", rule="#2D4152", tint="#1F3142",
                 series=["#6DA361", "#17A1C8", "#9C7300", "#D17276", "#559ACA"]),
}
GREEN, BLUE, OCHRE, RED, STEEL = range(5)


def text(x, y, s, size, fill, anchor="start", weight=None, family=None):
    """family None inherits the canvas face (Plex Mono); "sans" sets Plex Sans."""
    extra = ""
    if anchor != "start":
        extra += f' text-anchor="{anchor}"'
    if weight:
        extra += f' font-weight="{weight}"'
    if family == "sans":
        extra += f" font-family='\"{FACES['sans']}\", {SANS}'"
    return f'<text x="{x:g}" y="{y:g}" font-size="{size}" fill="{fill}"{extra}>{escape(s)}</text>'


def rect(x, y, w, h, fill, rx=2):
    return f'<rect x="{x:.1f}" y="{y:g}" width="{max(w, 0):.1f}" height="{h:g}" rx="{rx}" fill="{fill}"/>'


def fit(s, size, width, family="mono", weight=None):
    """Split a string into lines that fit a width at this font size."""
    if family == "mono":
        return textwrap.wrap(s, max(int(width / (size * CH)), 1), break_on_hyphens=False)
    lines, line = [], ""
    for word in s.split():
        trial = f"{line} {word}" if line else word
        if line and measure(trial, size, family, weight) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + [line] if line else lines


def para(x, y, s, size, fill, width, weight=None, family="mono"):
    """Wrapped text from baseline y. Returns (elements, next baseline)."""
    lines = fit(s, size, width, family, weight)
    lead = size + 5
    fam = family if family != "mono" else None
    return ([text(x, y + i * lead, line, size, fill, weight=weight, family=fam) for i, line in enumerate(lines)],
            y + len(lines) * lead)


def note(y, s, c):
    return para(M, y, s, 12, c["ink2"], R - M, family="sans")


def head(title, c):
    """Chart title and rule. Returns (elements, next baseline)."""
    b, y = para(M, 30, title, 15, c["ink"], R - M, weight=600, family="sans")
    b.append(f'<line x1="{M}" y1="{y - 8}" x2="{R}" y2="{y - 8}" stroke="{c["rule"]}"/>')
    return b, y + 16


def svg(h, title, desc, body, c):
    inner = "\n".join(body)
    return (
        f'<svg viewBox="0 0 {W} {h:g}" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'font-family=\'"{FACES["mono"]}", {MONO}\'>\n<title>{escape(title)}</title>\n<desc>{escape(desc)}</desc>\n'
        + embed(inner)
        + f'<rect width="{W}" height="{h:g}" rx="6" fill="{c["paper"]}"/>\n'
        + inner + "\n</svg>\n"
    )


def height(s):
    """Canvas height of an SVG string, from its viewBox."""
    return float(re.search(r'viewBox="0 0 [\d.]+ ([\d.]+)"', s).group(1))


def pair(left, right, c, steps=100):
    """Two charts at one height, so the pair sits level (D-262).
    left and right take (c, spread, h) and return SVG text. The shorter one
    opens its spacing until it reaches its partner; both then pad to the
    taller height. Returns (left SVG, right SVG)."""
    fns, sp = (left, right), [0.0, 0.0]
    hs = [height(left(c)), height(right(c))]
    if hs[0] != hs[1]:
        i = 0 if hs[0] < hs[1] else 1
        for k in range(1, steps + 1):
            sp[i] = k / steps
            hs[i] = height(fns[i](c, sp[i]))
            if hs[i] >= hs[1 - i]:
                break
    h = max(hs)
    return left(c, sp[0], h), right(c, sp[1], h)


def arrow(points, colour, c, dashed=False, width=1.5):
    """Line through the points with a head at the last one."""
    (x1, y1), (x2, y2) = points[-2], points[-1]
    d = "M" + " L".join(f"{x:g} {y:g}" for x, y in points)
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    if x1 == x2:  # vertical last segment
        s = 1 if y2 > y1 else -1
        tip = f"{x2 - 5:g},{y2 - 8 * s:g} {x2 + 5:g},{y2 - 8 * s:g} {x2:g},{y2:g}"
    else:
        s = 1 if x2 > x1 else -1
        tip = f"{x2 - 8 * s:g},{y2 - 5:g} {x2 - 8 * s:g},{y2 + 5:g} {x2:g},{y2:g}"
    return (f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{width}"{dash}/>'
            f'<polygon points="{tip}" fill="{colour}"/>')


def tag(x, y, s, fill, c, anchor="middle"):
    """A label on a paper patch, so it stays readable over a line. The text is
    ink2 (D-273); fill is the line's colour and stays on the line."""
    w = len(s) * 12 * CH + 10
    x0 = x - w / 2 if anchor == "middle" else x - 4
    return rect(x0, y - 13, w, 18, c["paper"], rx=3) + text(x, y, s, 12, c["ink2"], anchor=anchor)


def kind(c):
    """Outline colour for each kind of box."""
    s = c["series"]
    return dict(backend=s[GREEN], database=s[STEEL], cloud=s[OCHRE], external=c["ink2"],
                security=s[RED], bus=s[BLUE])


def box_lines(sub, extra, w):
    return fit(sub, 12, w - 16), (fit(extra, 12, w - 16) if extra else [])


def box_h(sub, extra, w):
    a, b = box_lines(sub, extra, w)
    return 38 + 16 * (len(a) + len(b))


def box(x, y, w, h, label, sub, extra, k, c):
    """A labelled box: name, description lines, and an optional third line in ink.
    The kind's colour is the outline (D-273: text wears ink or ink2)."""
    col = kind(c)[k]
    a, e = box_lines(sub, extra, w)
    b = [f'<rect x="{x}" y="{y:g}" width="{w}" height="{h:g}" rx="5" fill="{c["tint"]}" stroke="{col}" stroke-width="1.5"/>',
         text(x + w / 2, y + 23, label, 12.5, c["ink"], anchor="middle", weight=600)]
    for i, line in enumerate(a):
        b.append(text(x + w / 2, y + 41 + i * 16, line, 12, c["ink2"], anchor="middle"))
    for i, line in enumerate(e):
        b.append(text(x + w / 2, y + 41 + (len(a) + i) * 16, line, 12, c["ink"], anchor="middle"))
    return b


def region(x, y, w, h, c):
    return (f'<rect x="{x}" y="{y:g}" width="{w}" height="{h:g}" rx="8" fill="none" '
            f'stroke="{c["series"][OCHRE]}" stroke-dasharray="7 5"/>')


def legend(y, entries, c):
    """Two-column key. entries: (kind, label). Returns (elements, next y)."""
    b = [text(M, y, "Legend", 12.5, c["ink"], weight=600)]
    for i, (k, label) in enumerate(entries):
        x, yy = (M, 188)[i % 2], y + 22 + (i // 2) * 22
        b.append(f'<rect x="{x}" y="{yy - 10}" width="16" height="11" rx="2.5" fill="{c["tint"]}" stroke="{kind(c)[k]}" stroke-width="1.5"/>')
        b.append(text(x + 24, yy, label, 12, c["ink2"]))
    return b, y + 22 + ((len(entries) + 1) // 2) * 22


def deploys(d, c, spread=0.0, h=0):
    """What the kit deploys: client and registry outside the cluster, four parts inside.
    Fixed layout: spread is accepted for pair() and unused."""
    ink2, bw = c["ink2"], 148
    xl, xr = 24, 188
    b = []
    y1 = 16
    h1 = max(box_h(d["client"][1], None, 156), box_h(d["ngc"][1], None, 156))
    b += box(16, y1, 156, h1, *d["client"], None, "external", c)
    b += box(188, y1, 156, h1, *d["ngc"], None, "external", c)
    y2 = y1 + h1 + 48
    h2 = box_h(d["nim"][1], d["nim"][2], 312)
    y3 = y2 + h2 + 48
    h3 = max(box_h(d["cache"][1], None, bw), box_h(d["gpu"][1], d["gpu"][2], bw))
    y4 = y3 + h3 + 48
    h4 = box_h(d["autoscaler"][1], None, bw)
    b.append(region(8, y2 - 14, 344, y4 + h4 + 14 - (y2 - 14), c))
    b.append(arrow([(94, y1 + h1), (94, y2)], c["series"][GREEN], c, width=2))
    b.append(tag(94, y1 + h1 + 27, "OpenAI-compatible API", c["series"][GREEN], c))
    b.append(arrow([(266, y1 + h1), (266, y2)], ink2, c))
    b.append(tag(266, y1 + h1 + 27, "image pull", ink2, c))
    b += box(xl, y2, 312, h2, *d["nim"], "backend", c)
    b.append(arrow([(xl + bw / 2, y2 + h2), (xl + bw / 2, y3)], ink2, c))
    b.append(tag(xl + bw / 2, y2 + h2 + 27, "model files", ink2, c))
    b.append(arrow([(xr + bw / 2, y2 + h2), (xr + bw / 2, y3)], ink2, c))
    b.append(tag(xr + bw / 2, y2 + h2 + 27, "scheduled on", ink2, c))
    b += box(xl, y3, bw, box_h(d["cache"][1], None, bw), *d["cache"], None, "database", c)
    b += box(xr, y3, bw, h3, *d["gpu"], "cloud", c)
    b.append(arrow([(xr + bw / 2, y4), (xr + bw / 2, y3 + h3)], c["series"][BLUE], c, dashed=True))
    b.append(tag(xr + bw / 2, y3 + h3 + 27, "adds and removes", c["series"][BLUE], c))
    b += box(xr, y4, bw, h4, *d["autoscaler"], None, "cloud", c)
    lines = fit(d["cluster"], 12, 156)
    for i, line in enumerate(lines):
        b.append(text(20, y4 + h4 - 4 - (len(lines) - 1 - i) * 17, line, 12, c["ink"], weight=600))
    leg, y = legend(y4 + h4 + 42, [("backend", "Backend"), ("database", "Database"),
                                   ("cloud", "Cloud"), ("external", "External")], c)
    return svg(max(y, h), d["title"], d["desc"], b + leg, c)


def runner_ends(n, c, spread=0.0, pad=0):
    """How the runner ends: the runner's steps on the left, the watchdog on the right.
    Fixed layout: spread is accepted for pair() and unused; pad is the height to pad to."""
    ink2, bw = c["ink2"], 148
    xl, xr = 16, 196
    cl, cr = xl + bw / 2, xr + bw / 2

    def h(key):
        return box_h(n[key][1], n[key][2], bw)

    top = 12
    y1 = top + 30
    r1 = max(h("preflight"), h("arm"))
    y2 = y1 + r1 + 34
    y3 = y2 + h("steps") + 34
    y4 = y3 + h("teardown") + 34
    r4 = max(h("confirm"), h("takeover"))
    y5 = y4 + r4 + 56
    b = [region(8, top, 164, y5 + h("done") + 12 - top, c),
         region(188, top, 164, y4 + r4 + 12 - top, c),
         text(18, top + 19, n["lanes"][0], 12, c["ink"], weight=600),
         text(194, top + 19, n["lanes"][1], 12, c["ink"], weight=600)]
    b.append(arrow([(xl + bw, y1 + 27), (xr, y1 + 27)], ink2, c))
    b.append(arrow([(cr - 34, y1 + h("arm")), (cr - 34, y1 + r1 + 17), (cl, y1 + r1 + 17), (cl, y2)], ink2, c))
    b.append(arrow([(cl, y2 + h("steps")), (cl, y3)], ink2, c))
    b.append(arrow([(cl, y3 + h("teardown")), (cl, y4)], ink2, c))
    b.append(arrow([(cr + 30, y1 + h("arm")), (cr + 30, y4)], c["series"][BLUE], c, dashed=True))
    b.append(tag(cr + 30, (y2 + y4) / 2, "takes over", c["series"][BLUE], c))
    b.append(arrow([(xr, y4 + 27), (xl + bw, y4 + 27)], ink2, c))
    b.append(arrow([(cl - 30, y4 + h("confirm")), (cl - 30, y5)], c["series"][GREEN], c, width=2))
    b.append(tag(cl - 20, y4 + h("confirm") + 22, "yes", c["series"][GREEN], c, anchor="start"))
    turn = y4 + r4 + 34
    b.append(arrow([(cl + 30, y4 + h("confirm")), (cl + 30, turn), (cr, turn), (cr, y5)], c["series"][RED], c, dashed=True))
    b.append(tag(cl + 40, y4 + h("confirm") + 22, "no", c["series"][RED], c, anchor="start"))
    for key, x, y in (("preflight", xl, y1), ("arm", xr, y1), ("steps", xl, y2), ("teardown", xl, y3),
                      ("confirm", xl, y4), ("takeover", xr, y4), ("done", xl, y5), ("manual", xr, y5)):
        label, sub, extra, k = n[key]
        b += box(x, y, bw, h(key), label, sub, extra, k, c)
    leg, y = legend(y5 + max(h("done"), h("manual")) + 40,
                    [("backend", "Runner step"), ("security", "Check"), ("bus", "Watchdog action"),
                     ("cloud", "Clean exit"), ("external", "Manual follow-up")], c)
    return svg(max(y, pad), n["title"], n["desc"], b + leg, c)


def measured(m, c, spread=0.0, h=0):
    """Paired bars, one panel per measure. m: title, names, panels, desc, note.
    spread opens the gap between panels."""
    colours = [c["series"][GREEN], c["series"][BLUE]]
    b, y = head(m["title"], c)
    for label, rows in m["panels"]:
        lines, y = para(M, y, label, 13, c["ink"], R - M, weight=600)
        b += lines
        top = max(v for v, _ in rows)
        for j, (v, shown) in enumerate(rows):
            b.append(text(M, y + 4, m["names"][j], 12, c["ink2"]))
            b.append(text(R, y + 4, shown, 12, c["ink"], anchor="end"))
            b.append(rect(M, y + 11, R - M, 14, c["tint"]))
            b.append(rect(M, y + 11, (R - M) * v / top, 14, colours[j]))
            y += 44
        y += 10 + round(40 * spread)
    b.append(f'<line x1="{M}" y1="{y - 12}" x2="{R}" y2="{y - 12}" stroke="{c["rule"]}"/>')
    lines, y = note(y + 10, m["note"], c)
    return svg(max(y, h), m["title"], m["desc"], b + lines, c)


def panels(d, c, spread=0.0, h=0):
    """Small multiples on one shared scale: one panel per item, one bar per row,
    so every bar compares with every other (the ggplot2 trial, 2026-10-02).
    d: title, sub, panels [(label, colour, [(row, value, shown), ...])], notes,
    desc. colour is a series index or a token name, or a list of them, one per
    row. A panel with one unnamed row puts its value on the label line. spread
    opens the gap between panels."""
    top = max(v for _, _, rows in d["panels"] for _, v, _ in rows)
    b, y = head(d["title"], c)
    sub, y = para(M, y - 2, d["sub"], 12, c["ink2"], R - M)
    b += sub
    y += 8
    for i, (label, colour, rows) in enumerate(d["panels"]):
        y += round(40 * spread) if i else 0
        fills = colour if isinstance(colour, (list, tuple)) else [colour] * len(rows)
        b.append(text(M, y, label, 13, c["ink"], weight=600))
        for (name, v, shown), k in zip(rows, fills):
            fill = c["series"][k] if isinstance(k, int) else c[k]
            if name:  # a named row gets its own text line
                y += 20
                b.append(text(M, y, name, 12, c["ink2"]))
            b.append(text(R, y, shown, 12, c["ink"], anchor="end"))
            b.append(rect(M, y + 6, R - M, 12, c["tint"]))
            b.append(rect(M, y + 6, (R - M) * v / top, 12, fill))
            y += 18
        y += 24
    b.append(f'<line x1="{M}" y1="{y - 16}" x2="{R}" y2="{y - 16}" stroke="{c["rule"]}"/>')
    y += 4
    for s in d["notes"]:
        lines, y = note(y, s, c)
        b += lines
        y += 4
    return svg(max(y, h), d["title"], d["desc"], b, c)


def autoscale(a, c, spread=0.0, h=0):
    """The GPU node pool going 0 to 1 to 0, with the two measured spans.
    spread makes the step boxes taller and the arrows between them longer."""
    steps = [("Pool at 0 nodes", "cluster up, no GPU"),
             ("NIM pod Pending", "asks for one GPU"),
             ("GPU node Ready", "autoscaler added it"),
             ("NIM serving", a["serving"]),
             ("Pool back at 0", "autoscaler removed it")]
    spans = {1: (a["up"], GREEN), 3: (a["down"], BLUE)}
    bh, gap = 46 + round(14 * spread), 36 + round(44 * spread)
    off = (bh - 46) / 2
    b, y = head("GPU node autoscaling, 0 to 1 to 0", c)
    y -= 12
    for i, (label, sub) in enumerate(steps):
        edge = c["series"][GREEN] if i in (0, 4) else c["ink2"]
        b.append(f'<rect x="{M}" y="{y}" width="{R - M}" height="{bh}" rx="4" fill="{c["tint"]}" stroke="{edge}"/>')
        b.append(text(M + 14, y + 19 + off, label, 13, c["ink"], weight=600))
        b.append(text(M + 14, y + 37 + off, sub, 12, c["ink2"]))
        if i < 4:
            label, colour = spans.get(i, ("", None))
            stroke = c["series"][colour] if label else c["ink2"]
            b.append(arrow([(M + 24, y + bh + 4), (M + 24, y + bh + gap - 4)], stroke, c, width=2 if label else 1.5))
            if label:
                b.append(text(M + 42, y + bh + gap / 2 + 5, label, 13, c["ink"], weight=600))
            y += bh + gap
    lines, y = note(y + bh + 22, a["foot"], c)
    return svg(max(y, h), "GPU node autoscaling, 0 to 1 to 0", a["desc"], b + lines, c)




def steps(d, c, spread=0.0, h=0):
    """A vertical chain of boxes joined by arrows: a request path, a pipeline.
    d: title, steps [(label, sub, extra or None, kind)], note, desc; kind is a
    box kind ("backend", "database", ...). spread opens the gaps between boxes."""
    g = round(32 * spread)
    b, y = head(d["title"], c)
    y -= 10
    for i, (label, sub, extra, k) in enumerate(d["steps"]):
        bh = box_h(sub, extra, R - M)
        b += box(M, y, R - M, bh, label, sub, extra, k, c)
        y += bh
        if i < len(d["steps"]) - 1:
            b.append(arrow([((M + R) / 2, y + 2), ((M + R) / 2, y + 20 + g)], c["ink2"], c))
            y += 24 + g
    if d.get("note"):
        lines, y = note(y + 26, d["note"], c)
        b += lines
    else:
        y += 16
    return svg(max(y, h), d["title"], d["desc"], b, c)
