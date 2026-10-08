#!/usr/bin/env python3
"""Assemble the self-contained page: inject the data file and the view scripts into web/template.html.

Needs nothing but Python 3: whoever receives storm_explorer_data.js can rebuild the page.
Usage: python assemble.py [--config storm_explorer_config.py]
"""
import argparse, importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
APPS = ["detection", "damage", "ddamage", "forcings", "views"]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--config", default=os.path.join(HERE, "storm_explorer_config.py"))
    a = ap.parse_args()
    spec = importlib.util.spec_from_file_location("cfg", a.config); cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    base = os.path.dirname(os.path.abspath(a.config))
    data = os.path.join(base, cfg.OUTPUT_DATA)
    if not os.path.exists(data):
        raise SystemExit(f"{data} not found: run build_data.py first")
    read = lambda p: open(p, encoding="utf-8").read().replace("</script", "<\\/script")
    t = open(os.path.join(HERE, "web", "template.html"), encoding="utf-8").read()
    parts = {"/*__DATA__*/": read(data), "/*__FILL__*/": read(os.path.join(HERE, "web", "fill.js"))}
    parts.update({f"/*__APP_{k}__*/": read(os.path.join(HERE, "web", f"{k}.js")) for k in APPS})
    for mark, body in parts.items():
        assert t.count(mark) == 1, mark
        t = t.replace(mark, body)
    html = ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{cfg.TITLE}</title>\n</head>\n<body>\n{t}\n</body>\n</html>\n")
    out = os.path.join(base, cfg.OUTPUT_HTML)
    open(out, "w", encoding="utf-8").write(html)
    print(f"wrote {out} ({len(html.encode()) / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
