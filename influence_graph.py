#!/usr/bin/env uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "requests>=2.31",
#   "beautifulsoup4>=4.12",
# ]
# ///

import sys
import time
from collections import defaultdict, deque
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

UA = "PLInfluenceGraph/1.0 (educational; +https://github.com)"
API = "https://en.wikipedia.org/w/api.php"
DELAY = 0.7
OUT = "programming_language_influence.md"
HTML_OUT = "index.html"
MAX_NODES = 1_000


def api(params):
    params["format"] = "json"
    for a in range(3):
        try:
            r = requests.get(API, params=params, headers={"User-Agent": UA}, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception:
            if a == 2:
                return {}
            time.sleep(2 ** a)
    return {}


def section_html(title):
    d = api({"action": "parse", "page": title, "prop": "text", "section": 0, "redirects": True})
    return d.get("parse", {}).get("text", {}).get("*", ""), d.get("parse", {}).get("title", title)


def page_html(title):
    d = api({"action": "parse", "page": title, "prop": "text", "redirects": True})
    return d.get("parse", {}).get("text", {}).get("*", ""), d.get("parse", {}).get("title", title)


def resolve_chain(entries):
    m = {}
    for e in entries:
        m[e["from"]] = e["to"]
    for k in list(m.keys()):
        v = m[k]
        while v in m:
            v = m[v]
        m[k] = v
    return m


def batch_resolve(titles):
    m = {}
    for i in range(0, len(titles), 50):
        b = titles[i:i + 50]
        d = api({"action": "query", "titles": "|".join(b), "redirects": True})
        if not d:
            for o in b:
                m[o] = o
            continue
        chain = resolve_chain(
            d.get("query", {}).get("normalized", []) + d.get("query", {}).get("redirects", [])
        )
        for o in b:
            m[o] = chain.get(o, o)
        time.sleep(DELAY * 0.3)
    return m


def get_timeline():
    html, _ = page_html("Timeline_of_programming_languages")
    soup = BeautifulSoup(html, "html.parser")
    langs = {}
    for tbl in soup.find_all("table", class_="wikitable"):
        for row in tbl.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            for a in cells[1].find_all("a", href=True):
                h = a["href"]
                if not h.startswith("/wiki/") or ":" in h[6:]:
                    continue
                t = unquote(h[6:].split("#")[0])
                d = a.get_text(strip=True)
                if t and d and t not in langs:
                    langs[t] = d
    return langs


def extract_influenced(html):
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    ib = soup.find("table", class_="infobox")
    if not ib:
        return []
    rows = ib.find_all("tr")
    for i, row in enumerate(rows):
        th = row.find("th")
        if th and "influenced by" in th.get_text(strip=True).lower():
            # Content is in the next row (<td colspan="2">)
            if i + 1 < len(rows):
                td = rows[i + 1].find("td")
                if td:
                    result = []
                    for a in td.find_all("a", href=True):
                        h = a["href"]
                        if h.startswith("/wiki/") and ":" not in h[6:]:
                            result.append(unquote(h[6:].split("#")[0]))
                    return result
    return []


def norm(t):
    t = unquote(t.replace("_", " "))
    return t[0].upper() + t[1:] if t else t


def simp(t):
    if "(" in t and t.endswith(")"):
        b = t[:t.rindex("(")].strip()
        if b:
            return b
    return t


LONG_NAME_ABBREVIATIONS = {
    "Document_Style_Semantics_and_Specification_Language": "DSSSL",
    "Jet_Pulsion_Laboratory_Display_Information_System": "JPLDIS",
    "Communicating_sequential_processes": "CSP",
    "Semi-Automatic_Ground_Environment": "SAGE",
    "Polymorphic_Programming_Language": "PPL",
    "Information_Processing_Language": "IPL",
    "Common_Lisp_Object_System": "CLOS",
}


def abbreviate_name(wiki_title, display_name):
    if wiki_title in LONG_NAME_ABBREVIATIONS:
        return LONG_NAME_ABBREVIATIONS[wiki_title]
    if len(display_name) > 35:
        return simp(display_name)
    return display_name


def bundle_edge_lines(edges, ids):
    filtered = [(src, dst) for src, dst in edges if src in ids and dst in ids]
    edge_set = set(filtered)
    used = set()
    lines = []
    junction_styles = []
    junction_count = 0

    def new_junction():
        nonlocal junction_count
        jid = f"_J{junction_count}"
        junction_count += 1
        return jid

    # Step 1: Bidirectional pairs → two separate thick arrows
    for src, dst in filtered:
        if (src, dst) in used or (dst, src) in used:
            continue
        if (dst, src) in edge_set and src != dst:
            used.add((src, dst))
            used.add((dst, src))
            a, b = sorted([src, dst])
            lines.append(f"    {ids[a]} ==> {ids[b]}")
            lines.append(f"    {ids[b]} ==> {ids[a]}")

    # Step 2: Group remaining by source (fan-out via junction nodes for ≥2 targets)
    source_groups = defaultdict(set)
    for src, dst in filtered:
        if (src, dst) not in used:
            source_groups[src].add(dst)

    for src, targets in source_groups.items():
        if len(targets) <= 1:
            continue
        jid = new_junction()
        lines.append(f'    {ids[src]} --> {jid}((" "))')
        tlist = " & ".join(sorted(targets, key=lambda t: ids[t]))
        lines.append(f"    {jid} --> {tlist}")
        junction_styles.append(f"    style {jid} height:10px,width:10px,fill:#c0392b,stroke:#333,stroke-width:1px")
        for dst in targets:
            used.add((src, dst))

    # Step 3: Multiple sources → same target (fan-in via junction nodes for ≥2 sources)
    target_groups = defaultdict(set)
    for src, dst in filtered:
        if (src, dst) not in used:
            target_groups[dst].add(src)

    for dst, srcs in target_groups.items():
        if len(srcs) <= 1:
            for src in srcs:
                if (src, dst) not in used:
                    lines.append(f"    {ids[src]} --> {ids[dst]}")
                    used.add((src, dst))
            continue
        jid = new_junction()
        slist = " & ".join(sorted(srcs, key=lambda s: ids[s]))
        lines.append(f'    {slist} --- {jid}((" "))')
        lines.append(f"    {jid} --> {ids[dst]}")
        junction_styles.append(f"    style {jid} height:10px,width:10px,fill:#c0392b,stroke:#333,stroke-width:1px")
        for src in srcs:
            used.add((src, dst))

    lines.extend(junction_styles)
    return lines


def diagram(nodes, edges, names):
    s = sorted(nodes)
    ids = {n: f"N{i}" for i, n in enumerate(s)}

    node_colors = compute_node_colors(list(ids.values()), [(ids[src], ids[dst]) for src, dst in edges if src in ids and dst in ids])

    L = ["# Programming Language Influence Graph", "", "```mermaid", "flowchart TD"]
    for n in s:
        d = abbreviate_name(n, names.get(n, simp(n))).replace('"', "'")
        wiki_url = f"https://en.wikipedia.org/wiki/{n.replace(' ', '_')}"
        L.append(f'    {ids[n]}["<a href=\'{wiki_url}\'>{d}</a>"]')
    L.append("")
    L.append("")
    for line in bundle_edge_lines(edges, ids):
        L.append(line)

    L.append("")
    for n in s:
        nid = ids[n]
        c = node_colors.get(nid, (200, 200, 200))
        L.append(f'    style {nid} fill:#{int(c[0]):02x}{int(c[1]):02x}{int(c[2]):02x},stroke:#333')

    L.append("```")
    L.append(f"\n*{len(nodes)} languages, {len(edges)} influences*")
    return "\n".join(L)


def hsl_to_hex(h, s, l):
    s /= 100
    l /= 100
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    r, g, b = int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)
    return f"#{r:02x}{g:02x}{b:02x}"


def hsl_to_rgb(h, s, l):
    s /= 100
    l /= 100
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)


def blend_colors(colors_list):
    if not colors_list:
        return (200, 200, 200)
    r = sum(c[0] for c in colors_list) / len(colors_list)
    g = sum(c[1] for c in colors_list) / len(colors_list)
    b = sum(c[2] for c in colors_list) / len(colors_list)
    return (r, g, b)


def compute_node_colors(node_ids, edges):
    children = defaultdict(set)
    parents = defaultdict(set)
    for src, dst in edges:
        children[src].add(dst)
        parents[dst].add(src)

    root_nodes = sorted([n for n in node_ids if not parents[n]])
    num_roots = len(root_nodes)
    node_colors = {}

    for i, root in enumerate(root_nodes):
        hue = (i * 360 / num_roots) % 360
        node_colors[root] = hsl_to_rgb(hue, 50, 75)

    queue = deque(root_nodes)
    visited = set(root_nodes)
    while queue:
        node = queue.popleft()
        for child in children[node]:
            if child not in node_colors:
                parent_rgbs = [node_colors[p] for p in parents[child] if p in node_colors]
                if parent_rgbs:
                    node_colors[child] = blend_colors(parent_rgbs)
            if child not in visited:
                visited.add(child)
                queue.append(child)

    for n in node_ids:
        if n not in node_colors:
            node_colors[n] = (200, 200, 200)

    return node_colors


def html_diagram(nodes, edges, names):
    s = sorted(nodes)
    ids = {n: f"N{i}" for i, n in enumerate(s)}

    node_colors = compute_node_colors(list(ids.values()), [(ids[src], ids[dst]) for src, dst in edges if src in ids and dst in ids])

    flowchart = ["%%{init: {'flowchart': {'nodeSpacing': 150, 'rankSpacing': 200, 'diagramMarginX': 10, 'diagramMarginY': 10, 'curve': 'stepAfter', 'defaultRenderer': 'elk'}, 'maxTextSize': 900000}}%%", "flowchart-elk TD"]
    for n in s:
        d = abbreviate_name(n, names.get(n, simp(n))).replace('"', "'")
        wiki_url = f"https://en.wikipedia.org/wiki/{n.replace(' ', '_')}"
        flowchart.append(f'    {ids[n]}["<a href=\'{wiki_url}\'>{d}</a>"]')
    flowchart.append("")
    for line in bundle_edge_lines(edges, ids):
        flowchart.append(line)

    flowchart.append("")
    for n in s:
        nid = ids[n]
        c = node_colors.get(nid, (200, 200, 200))
        flowchart.append(f'    style {nid} fill:#{int(c[0]):02x}{int(c[1]):02x}{int(c[2]):02x},stroke:#333')

    flowchart_str = "\n".join(flowchart)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Programming Language Influence Graph</title>
    <script src="https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk/dist/mermaid-layout-elk.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
    <script>
        mermaid.initialize({{
            startOnLoad: true,
            theme: 'default',
            maxEdges: 10000,
            maxTextSize: 900000,
            flowchart: {{
                useMaxWidth: false,
                useMaxHeight: false,
                securityLevel: 'loose',
                htmlLabels: true,
                nodeSpacing: 150,
                rankSpacing: 200,
                defaultRenderer: 'elk',
                padding: 20
            }}
        }});

        let currentZoom = 1;
        let fitMode = 'fill';

        function autoFit() {{
            var wrapper = document.querySelector('.diagram-wrapper');
            var container = document.getElementById('diagram-container');
            var svg = container ? container.querySelector('svg') : null;
            if (!svg || !wrapper) return;

            var wrapW = wrapper.clientWidth;
            var wrapH = wrapper.clientHeight;

            if (!svg.getAttribute('viewBox')) {{
                var bb = svg.getBBox();
                svg.setAttribute('viewBox', bb.x + ' ' + bb.y + ' ' + bb.width + ' ' + bb.height);
            }}

            container.style.display = 'block';
            container.style.width = wrapW + 'px';
            container.style.height = wrapH + 'px';
            container.style.overflow = 'hidden';
            container.style.padding = '0';

            svg.setAttribute('width', wrapW);
            svg.setAttribute('height', wrapH);
            svg.style.width = wrapW + 'px';
            svg.style.height = wrapH + 'px';
            svg.style.maxWidth = 'none';
            svg.setAttribute('preserveAspectRatio', 'none');

            fitMode = 'fill';
            var zoomLevel = document.getElementById('zoom-level');
            if (zoomLevel) zoomLevel.textContent = 'Fit';
        }}

        document.addEventListener('DOMContentLoaded', function() {{
            setTimeout(function() {{
                autoFit();
            }}, 1500);

            var wrapper = document.querySelector('.diagram-wrapper');
            if (wrapper) {{
                wrapper.addEventListener('wheel', function(e) {{
                    if (e.ctrlKey || e.metaKey) {{
                        e.preventDefault();
                        var delta = e.deltaY > 0 ? -0.05 : 0.05;
                        currentZoom = Math.max(0.02, Math.min(100, currentZoom + delta));
                        fitMode = 'zoom';
                        applyZoomManual();
                    }}
                }}, {{ passive: false }});
            }}
        }});

        function applyZoomManual() {{
            var container = document.getElementById('diagram-container');
            var svg = container ? container.querySelector('svg') : null;
            var wrapper = document.querySelector('.diagram-wrapper');
            var zoomLevel = document.getElementById('zoom-level');
            if (svg) {{
                svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
                svg.style.width = '';
                svg.style.height = '';
            }}
            if (container) {{
                container.style.display = 'inline-block';
                container.style.width = '';
                container.style.height = '';
                container.style.overflow = '';
                container.style.padding = '';
                container.style.zoom = currentZoom;
            }}
            if (wrapper) {{
                wrapper.style.overflow = 'auto';
            }}
            if (zoomLevel) {{
                zoomLevel.textContent = Math.round(currentZoom * 100) + '%';
            }}
        }}

        function resetZoom() {{
            autoFit();
        }}

        function zoomIn() {{
            currentZoom = Math.min(100, currentZoom + 0.1);
            fitMode = 'zoom';
            applyZoomManual();
        }}

        function zoomOut() {{
            currentZoom = Math.max(0.02, currentZoom - 0.1);
            fitMode = 'zoom';
            applyZoomManual();
        }}
    </script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 95%;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.1);
            padding: 30px;
        }}
        h1 {{
            color: #333;
            margin-bottom: 10px;
            text-align: center;
        }}
        .info {{
            color: #666;
            text-align: center;
            margin-bottom: 20px;
            font-size: 14px;
        }}
        .diagram-wrapper {{
            overflow: auto;
            margin: 20px 0;
            border: 1px solid #eee;
            background: #fafafa;
            position: relative;
            height: calc(100vh - 180px);
            min-height: 500px;
            width: 100%;
        }}
        #diagram-container {{
            display: block;
            overflow: hidden;
        }}
        .mermaid {{
            display: block;
        }}
        .mermaid .edgePath .path.thick {{
            stroke: #c0392b !important;
            stroke-width: 3px !important;
        }}
        .mermaid .node foreignObject div {{
            display: inline-block !important;
            width: auto !important;
            white-space: nowrap !important;
            overflow: visible !important;
        }}
        .mermaid .node foreignObject {{
            overflow: visible !important;
        }}
        .mermaid .node foreignObject a {{
            color: #0066cc !important;
            font-weight: 500;
            text-shadow: 1px 1px 2px rgba(255, 255, 255, 0.7), -1px -1px 2px rgba(255, 255, 255, 0.7), 1px -1px 2px rgba(255, 255, 255, 0.7), -1px 1px 2px rgba(255, 255, 255, 0.7) !important;
        }}
        .zoom-controls {{
            display: flex;
            gap: 5px;
            justify-content: flex-end;
            margin-bottom: 8px;
            background: white;
            padding: 8px;
            border-radius: 4px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }}
        .zoom-button {{
            padding: 6px 12px;
            border: 1px solid #ddd;
            background: white;
            cursor: pointer;
            border-radius: 3px;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.2s;
        }}
        .zoom-button:hover {{
            background: #f0f0f0;
            border-color: #999;
        }}
        .zoom-button:active {{
            background: #e0e0e0;
        }}
        .zoom-info {{
            padding: 6px 12px;
            background: #f5f5f5;
            border: 1px solid #ddd;
            border-radius: 3px;
            font-size: 12px;
            font-weight: 500;
            color: #666;
            min-width: 60px;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Programming Language Influence Graph</h1>
        <div class="info">{len(nodes)} languages, {len(edges)} influences</div>
        <div class="zoom-controls">
            <button class="zoom-button" onclick="zoomOut()">&#x2212;</button>
            <div class="zoom-info" id="zoom-level">100%</div>
            <button class="zoom-button" onclick="zoomIn()">+</button>
            <button class="zoom-button" onclick="resetZoom()">Fit</button>
        </div>
        <div class="diagram-wrapper">
            <div id="diagram-container">
                <div class="mermaid">
{flowchart_str}
                </div>
            </div>
        </div>
    </div>
</body>
</html>"""
    return html


def main():
    # --- Step 1: timeline languages ---
    print("1. Timeline languages...")
    raw_langs = get_timeline()
    print(f"   {len(raw_langs)} entries")

    # --- Step 2: resolve redirects, deduplicate ---
    print("2. Resolving redirects for timeline entries...")
    rm = batch_resolve(list(raw_langs.keys()))
    display = {}
    for o, c in rm.items():
        if c not in display or len(raw_langs[o]) < len(display[c]):
            display[c] = raw_langs[o]
    print(f"   Unique: {len(display)}")

    # --- Step 3: BFS crawl ---
    print("3. Crawling influence graph...")

    all_nodes = set(display.keys())
    processed = set()
    edges = []
    canon_cache = {}

    current_layer = list(display.keys())
    iteration = 0

    while len(processed) < MAX_NODES and current_layer:
        iteration += 1
        print(f"   Layer {iteration}: {len(current_layer)} languages")
        new_raw = set()

        for title in current_layer:
            if title in processed:
                continue
            processed.add(title)

            dsp = display.get(title, simp(title))
            print(f"      [{len(processed)}/{MAX_NODES}] {dsp}")

            try:
                html, _ = section_html(title)
            except Exception:
                html = ""

            ib = extract_influenced(html)
            for src_raw in ib:
                src = norm(src_raw)
                if src:
                    edges.append((src, title))
                    new_raw.add(src)

            time.sleep(DELAY)

        # Resolve redirects for newly discovered raw titles
        fresh = [r for r in new_raw if r not in canon_cache]
        if fresh:
            canon_cache.update(batch_resolve(fresh))

        # Canonicalize all edges and build next layer
        updated = []
        next_layer = set()
        for src, dst in edges:
            cs = canon_cache.get(src, src)
            updated.append((cs, dst))
            if cs not in all_nodes and cs not in processed:
                all_nodes.add(cs)
                next_layer.add(cs)
                if cs not in display:
                    display[cs] = simp(cs)
        edges = updated
        current_layer = list(next_layer)

    # Remove self-loops and deduplicate edges
    edges = list({(s, d) for s, d in edges if s != d})

    # Collect final node set
    all_nodes = {n for e in edges for n in e}

    print(f"\n   Processed: {len(processed)}")
    print(f"   Graph: {len(all_nodes)} nodes, {len(edges)} edges")

    # --- Step 4: diagram ---
    print("4. Generating diagram...")
    md = diagram(all_nodes, edges, display)
    with open(OUT, "w") as f:
        f.write(md)
    print(f"Done > {OUT}")
    
    html = html_diagram(all_nodes, edges, display)
    with open(HTML_OUT, "w") as f:
        f.write(html)
    print(f"Done > {HTML_OUT}")


if __name__ == "__main__":
    main()
