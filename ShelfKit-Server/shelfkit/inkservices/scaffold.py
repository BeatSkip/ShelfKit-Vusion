"""New app from the Apps tab's wizard: what goes in inkapps/<id>/.

    files(spec) -> {"app.py": "...", "layout.xml": "..."}   or raises SpecError

The spec is what the wizard collects:

    id            folder name and app id (lower-case letters, digits, - and _)
    title         the name on the Apps tab
    description   one line
    icon          an InkLayout icon name, or "" for none
    draw          "layout" (layout.xml, Python supplies data) or "python" (@app.render)
    timer_minutes 0 for none, else how often @app.every runs
    on_open       true: a function for an NFC tap
    fields        labels of the per-tag settings
    buttons       labels of the phone page's buttons

The code it writes runs as it is (the app loads, draws, and every button does
something visible), so a new app can be put on a tag straight away and then edited.
"""

from __future__ import annotations

import json
import keyword
import re

from ..inklayout import icons

ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
MAX_ITEMS = 12
MAX_LABEL = 60


class SpecError(ValueError):
    """The wizard sent something that cannot become an app; the message says what."""


def _slug(label: str, used: set[str], fallback: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or fallback
    if s[0].isdigit() or keyword.iskeyword(s):
        s = f"{fallback}_{s}"
    base, n = s, 2
    while s in used:
        s = f"{base}_{n}"
        n += 1
    used.add(s)
    return s


def _labels(spec: dict, key: str, what: str) -> list[str]:
    raw = spec.get(key) or []
    if not isinstance(raw, list):
        raise SpecError(f"{key} is a list of labels")
    labels = [str(x).strip() for x in raw if str(x).strip()]
    if len(labels) > MAX_ITEMS:
        raise SpecError(f"at most {MAX_ITEMS} {what}")
    for label in labels:
        if len(label) > MAX_LABEL:
            raise SpecError(f"{what[:-1]} label {label[:20]!r}... is longer than {MAX_LABEL}")
    return labels


def check(spec: dict) -> dict:
    """The spec cleaned up, or SpecError."""
    app_id = str(spec.get("id") or "").strip()
    if not ID_RE.fullmatch(app_id):
        raise SpecError("the folder name is 1-32 lower-case letters, digits, - and _, "
                        "starting with a letter or digit")
    title = str(spec.get("title") or "").strip()
    if not title:
        raise SpecError("the app needs a name")
    if len(title) > MAX_LABEL:
        raise SpecError(f"the name is longer than {MAX_LABEL} characters")
    icon = str(spec.get("icon") or "").strip()
    if icon and icon not in icons.names():
        raise SpecError(f"no icon {icon!r}; pick one of {', '.join(icons.names())}")
    draw = spec.get("draw") or "layout"
    if draw not in ("layout", "python"):
        raise SpecError("draw is layout or python")
    try:
        minutes = int(spec.get("timer_minutes") or 0)
    except (TypeError, ValueError):
        raise SpecError("timer_minutes is a whole number") from None
    if minutes < 0 or minutes > 7 * 24 * 60:
        raise SpecError("timer_minutes is between 1 and 10080 (a week), or 0 for none")
    return {"id": app_id, "title": title,
            "description": str(spec.get("description") or "").strip()[:200],
            "icon": icon, "draw": draw, "timer_minutes": minutes,
            "on_open": bool(spec.get("on_open")),
            "fields": _labels(spec, "fields", "settings"),
            "buttons": _labels(spec, "buttons", "buttons")}


def _q(s: str) -> str:
    """A Python string literal (JSON's is valid Python for any text)."""
    return json.dumps(s, ensure_ascii=False)


def files(spec: dict) -> dict[str, str]:
    s = check(spec)
    used = {"data", "draw", "refresh", "tapped", "app", "tag", "canvas"}
    fields = [(_slug(label, used, "setting"), label) for label in s["fields"]]
    buttons = [(_slug(label, used, "button"), label) for label in s["buttons"]]
    layout = s["draw"] == "layout"

    head = [f"app = InkApp({_q(s['id'])}, title={_q(s['title'])},"]
    head.append(f"             description={_q(s['description'])},")
    if s["icon"]:
        head.append(f"             icon={_q(s['icon'])},")
    if layout:
        head.append('             layout="layout.xml",')
    head[-1] = head[-1].rstrip(",") + ")"

    lines = [f'"""{s["id"]} - {s["description"] or s["title"]}', "",
             "Made with the Apps tab's New app wizard. Edit it, then press Reload apps.",
             "The screen is " + ("layout.xml (InkLayout); this file says what data it shows"
                                 if layout else "drawn in Python by draw()") + ".",
             '"""', "", "from shelfkit.inkservices import InkApp", "", *head]
    for key, label in fields:
        lines.append(f"app.config_field({_q(key)}, label={_q(label)}, default=\"\")")

    def values(indent: str) -> list[str]:
        out = [f"{indent}\"title\": {_q(s['title'])},"]
        out += [f"{indent}{_q(key)}: tag.config.get({_q(key)}, \"\")," for key, _ in fields]
        if s["on_open"]:
            out.append(f"{indent}\"taps\": tag.data.get(\"taps\", 0),")
        if buttons:
            out.append(f"{indent}\"last\": tag.data.get(\"last\", \"\"),")
        return out

    if layout:
        lines += ["", "", "@app.data", "def data(tag):",
                  '    """What layout.xml sees as `data`. Runs on every redraw: change nothing here."""',
                  "    return {", *values("        "), "    }"]
    else:
        lines += ["", "", "@app.render", "def draw(tag, canvas):",
                  "    d = {", *values("        "), "    }",
                  "    canvas.text((6, 6), tag.alias or tag.hex_id, size=16, bold=True)",
                  "    canvas.wrap((6, 32), d[\"title\"], size=18, bold=True)",
                  "    y = 90"]
        for key, label in fields:
            lines += [f"    canvas.text((6, y), {_q(label)} + \": \" + str(d[{_q(key)}]), size=12)",
                      "    y += 18"]
        if s["on_open"]:
            lines.append("    canvas.text((6, y), f\"Taps: {d['taps']}\", size=14, bold=True)")
            lines.append("    y += 22")
        if buttons:
            lines.append("    canvas.text((6, y), d[\"last\"], size=12)")
    if s["timer_minutes"]:
        lines += ["", "", f"@app.every(minutes={s['timer_minutes']})", "def refresh(tag):",
                  "    \"\"\"Fetch fresh data here, for example with tag.fetch_json(url), and keep",
                  "    it in tag.data. The screen is sent only if it changed.\"\"\"",
                  "    pass"]
    if s["on_open"]:
        lines += ["", "", "@app.on_open", "def tapped(tag):",
                  "    tag.data[\"taps\"] = tag.data.get(\"taps\", 0) + 1",
                  "    tag.log(f\"tapped ({tag.data['taps']})\")"]
    for name, label in buttons:
        lines += ["", "", f"@app.button({_q(label)})", f"def {name}(tag):",
                  f"    tag.data[\"last\"] = {_q('Pressed: ' + label)}"]
    out = {"app.py": "\n".join(lines) + "\n"}

    if layout:
        x = ['<screen padding="6" gap="6">',
             '  <row bg="black" padding="4 6" radius="3">']
        if s["icon"]:
            x.append(f'    <icon name="{s["icon"]}" color="white"/>')
        x += ['    <text color="white" bold="true" size="16">{{ tag.alias }}</text>',
              "  </row>",
              '  <text size="18" bold="true" fit="shrink" lines="2">{{ data.title }}</text>']
        for key, label in fields:
            x.append(f'  <text size="12" fit="shrink">{_xml(label)}: {{{{ data.{key} }}}}</text>')
        if s["on_open"]:
            x += ['  <col gap="0">', '    <text size="11">TAPS</text>',
                  '    <text size="48" bold="true" color="red">{{ data.taps }}</text>', "  </col>"]
        if buttons:
            x.append('  <text if="data.last" size="12" fit="wrap" lines="3">{{ data.last }}</text>')
        x += ['  <spacer h="fill"/>', "  <line/>",
              '  <text size="11" align="center">Edit inkapps/' + s["id"] + '/</text>', "</screen>"]
        out["layout.xml"] = "\n".join(x) + "\n"
    return out


def _xml(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("{", "(").replace("}", ")"))
