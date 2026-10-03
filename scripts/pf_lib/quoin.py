"""Quoin tokens for the Paper Forge console.

Emits the console's CSS custom properties for light, guarded
``prefers-color-scheme: dark`` and ``[data-theme="dark"]`` from the frozen
Quoin v2.0 values below. Set ``$QUOIN_ROOT`` to a Quoin design-system checkout
to read its ``quoin/tokens.json`` and its ``svgcharts`` mark stylesheet
instead; the console then also draws figures. Without it the build is
self-contained and the figures are left out.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

FROZEN = {  # Quoin v2.0, palette q1 Syme, ruled 2026-09-17
    "sans": '"Avenir Next", Inter, "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif',
    "mono": "IBM Plex Mono",
    "light": {"paper": "#F3F1EF", "card": "#FCFBF9", "ink": "#2B2926", "ink2": "#6A625A",
              "rule": "#D2CCC3", "rule2": "#E5E0D8", "signature": "#A57C2C", "accent": "#2E5F5A",
              "strategy": "#557459", "ai": "#1E5468", "governance": "#8A681E", "risk": "#8D3731",
              "data": "#5A707E", "tint": "#EBE6DD"},
    "dark": {"paper": "#0E1C2B", "card": "#19293B", "ink": "#E8E2D6", "ink2": "#A8A296",
             "rule": "#2D4152", "rule2": "#213344", "signature": "#CFA24E", "accent": "#7DB5AE",
             "strategy": "#B7C9B3", "ai": "#8CBFD3", "governance": "#D3AA55", "risk": "#D08284",
             "data": "#7B97AC", "tint": "#1F3142"},
    "tints": {"light_mix": 0.12, "dark_mix": 0.22},
    "domain_accents": {"light": {"paper-forge": "#1C4286"}, "dark": {"paper-forge": "#8FB0DC"}},
}
CATEGORIES = ("strategy", "ai", "governance", "risk", "data")
DOMAIN = "paper-forge"


def quoin_root() -> Path | None:
    """A Quoin checkout named by $QUOIN_ROOT, or None (opt-in)."""
    value = os.environ.get("QUOIN_ROOT")
    return Path(value) if value else None


def load_tokens() -> tuple[dict, str]:
    if quoin_root() is None:
        return FROZEN, "frozen v2.0"
    path = quoin_root() / "quoin" / "tokens.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")), str(path)
    except (OSError, ValueError) as error:
        print(f"quoin: {path} unreadable ({error}); frozen v2.0 tokens used", file=sys.stderr)
        return FROZEN, "frozen v2.0"


def _hex_mix(a: str, b: str, frac: float) -> str:
    """frac of a mixed into b (category into paper), the tokens.json tint rule."""
    ra, ga, ba = (int(a[i:i + 2], 16) for i in (1, 3, 5))
    rb, gb, bb = (int(b[i:i + 2], 16) for i in (1, 3, 5))
    mix = lambda x, y: round(x * frac + y * (1 - frac))
    return "#{:02X}{:02X}{:02X}".format(mix(ra, rb), mix(ga, gb), mix(ba, bb))


def _scheme(t: dict, scheme: str) -> str:
    c = t[scheme]
    accent = t["domain_accents"][scheme][DOMAIN]
    frac = t["tints"]["light_mix" if scheme == "light" else "dark_mix"]
    on_dark = scheme == "dark"
    # canonical Quoin names (svgcharts reads these) + category tints
    canon = [f"--{k}:{c[k]}" for k in ("paper", "card", "ink", "ink2", "rule", "rule2", "tint",
                                       "accent", "signature", *CATEGORIES)]
    canon += [f"--{k}-bg:{_hex_mix(c[k], c['paper'], frac)}" for k in CATEGORIES]
    canon.append(f"--domain-accent:{accent}")
    # the console's own names, kept so the stylesheet reads as before
    legacy = [
        f"--paper-deep:{c['tint']}", f"--ink-soft:{c['ink2']}", f"--line:{c['rule']}",
        f"--line-strong:color-mix(in srgb,{c['rule']} 55%,{c['ink2']})",
        f"--ember:{accent}", f"--ember-dark:color-mix(in srgb,{accent} 78%,{c['ink']})",
        f"--green:{c['accent']}", f"--green-soft:{_hex_mix(c['strategy'], c['paper'], frac)}",
        f"--gold-soft:{_hex_mix(c['governance'], c['paper'], frac)}",
        f"--blue-soft:{_hex_mix(c['ai'], c['paper'], frac)}",
        f"--glass:color-mix(in srgb,{c['card']} {'8%' if on_dark else '55%'},transparent)",
        f"--glass-strong:color-mix(in srgb,{c['card']} {'14%' if on_dark else '85%'},transparent)",
        f"--glass-edge:color-mix(in srgb,{c['card']} {'10%' if on_dark else '70%'},transparent)",
        f"--focus-ring:color-mix(in srgb,{c['accent']} 22%,transparent)",
        f"--ember-ring:color-mix(in srgb,{accent} {'40%' if on_dark else '30%'},transparent)",
        f"--grid-line:color-mix(in srgb,{c['ink']} {'7%' if on_dark else '4%'},transparent)",
        f"--watermark:color-mix(in srgb,{c['ink']} {'8%' if on_dark else '5%'},transparent)",
        f"--shadow:0 18px 60px color-mix(in srgb,{c['ink'] if not on_dark else '#000'} {'14%' if not on_dark else '45%'},transparent)",
        f"--shadow-soft:0 8px 24px color-mix(in srgb,{c['ink'] if not on_dark else '#000'} {'10%' if not on_dark else '35%'},transparent)",
        f"--shadow-dialog:0 30px 100px color-mix(in srgb,#000 {'35%' if not on_dark else '65%'},transparent)",
        f"--backdrop:color-mix(in srgb,{c['paper'] if on_dark else c['ink']} {'70%' if on_dark else '58%'},transparent)",
        f"--on-ink-soft:color-mix(in srgb,{c['paper']} 78%,transparent)",
    ]
    return ";".join(canon + legacy) + f";color-scheme:{scheme}"


def chart_css() -> str:
    """svgcharts.css() from a Quoin checkout by path import; empty when QUOIN_ROOT is unset."""
    if quoin_root() is None:
        return ""
    scripts = quoin_root() / "scripts"
    try:
        sys.path.insert(0, str(scripts))
        import svgcharts  # type: ignore  # noqa: WPS433
        return svgcharts.css()
    except Exception as error:  # noqa: BLE001 — any import or palette failure is non-fatal
        print(f"quoin: svgcharts unavailable under {scripts} ({error}); no chart CSS emitted", file=sys.stderr)
        return ""
    finally:
        if str(scripts) in sys.path:
            sys.path.remove(str(scripts))


def quoin_css(with_charts: bool = True) -> str:
    t, src = load_tokens()
    fonts = f'--sans:{t["sans"]};--mono:"{t["mono"]}",Menlo,monospace;--radius:18px'
    css = (f"/* Quoin {t.get('version', '2.0')} tokens ({src}) — domain accent {DOMAIN} */\n"
           f":root{{{_scheme(t, 'light')};{fonts}}}\n"
           f'@media(prefers-color-scheme:dark){{:root:not([data-theme="light"]){{{_scheme(t, "dark")}}}}}\n'
           f':root[data-theme="dark"]{{{_scheme(t, "dark")}}}')
    if with_charts:
        css += "\n" + chart_css()
    return css


if __name__ == "__main__":
    print(quoin_css())
