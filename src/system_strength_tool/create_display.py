"""
Multi-Map Grid Viewer Generator

Creates a single HTML page that embeds all discovered HTML maps in a
responsive grid layout. This makes it easy to compare the seven maps side by
side without switching files.

Keep the source HTML files in the same directory as this script.
"""

import os
import re
import sys
import argparse
import json
from pathlib import Path
import collections
import math

import pandas as pd
from map_display_utils import format_num, metric_global_range, normalize_position

# Configuration
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_FILENAME = "Strength_All_Grid.html"
FRAME_HEIGHT_PX = 420
FRAME_BORDER = "1px solid #ccc"


def build_shared_legend(keyword: str, strength_range):
    keyword_upper = keyword.upper()
    bright_green = "#00CC00"
    bright_red = "#FF0000"
    bright_yellow = "#FFEA00"
    dark_green = "#004D20"

    try:
        global_min, global_max = float(strength_range[0]), float(strength_range[1])
    except:
        return (
                    f"linear-gradient(90deg, {bright_red} 0%, {bright_yellow} 50%, {bright_green} 100%)",
                    '<div class="legend-tick" style="left: 0%;"><span class="legend-tick-line"></span><span class="legend-tick-label">Min</span></div>'
                    '<div class="legend-tick" style="left: 100%;"><span class="legend-tick-line"></span><span class="legend-tick-label">Max</span></div>',
                )
    
    if keyword_upper == "COMPARE":
        pos_0 = normalize_position(0.0, global_min, global_max)
        if pos_0 > 0.9:
            pos_0 = math.floor(pos_0*10)/10
        elif pos_0 < 0.1:
            pos_0 = math.ceil(pos_0*10)/10
        pos_0_pct = pos_0 * 100
        blend_width = 4
        red_to_yellow_start = max(0.0, pos_0_pct - 2*blend_width)
        red_to_yellow_end = min(100.0, pos_0_pct - blend_width)
        yellow_to_green_start = max(0.0, pos_0_pct + blend_width)
        yellow_to_green_end = min(100.0, pos_0_pct + 2*blend_width)

        if global_min >= 0 and global_max <= 0:
            legend_gradient = bright_yellow
        elif global_min >= 0:
            legend_gradient = (
                "linear-gradient(90deg, "
                f"{bright_yellow} 0%, "
                f"{bright_yellow} {yellow_to_green_start:.4f}%, "
                f"{bright_green} {yellow_to_green_end:.4f}%, "
                f"{bright_green} 100%)"
            )
        elif global_max <= 0:
            legend_gradient = (
                "linear-gradient(90deg, "
                f"{bright_red} 0%, "
                f"{bright_red} {red_to_yellow_start:.4f}%, "
                f"{bright_yellow} {red_to_yellow_end:.4f}%, "
                f"{bright_yellow} 100%)"
            )
        else:
            legend_gradient = (
                "linear-gradient(90deg, "
                f"{bright_red} 0%, "
                f"{bright_red} {red_to_yellow_start:.4f}%, "
                f"{bright_yellow} {red_to_yellow_end:.4f}%, "
                f"{bright_yellow} {yellow_to_green_start:.4f}%, "
                f"{bright_green} {yellow_to_green_end:.4f}%, "
                f"{bright_green} 100%)"
            )

        tick_specs = [
            (0.0, format_num(global_min)),
            (pos_0_pct, "0"),
            (100.0, format_num(global_max)),
        ]
    else:
        # Keep low-end legend ticks readable by using fixed visual anchor points.
        pos_3_pct = 20.0
        pos_5_pct = 30.0
        blend_width = 2.0

        red_to_yellow_start = max(0.0, pos_3_pct - blend_width)
        red_to_yellow_end = min(100.0, pos_3_pct + blend_width)
        yellow_to_green_start = max(0.0, pos_5_pct - blend_width)
        yellow_to_green_end = min(100.0, pos_5_pct + blend_width)

        pos_999 = normalize_position(999, global_min, global_max)
        pos_999_before = max(0.0, pos_999 - 1e-6)

        pos_999_pct = pos_999 * 100
        pos_999_before_pct = pos_999_before * 100

        legend_gradient = (
            "linear-gradient(90deg, "
            f"{bright_red} 0%, "
            f"{bright_red} {red_to_yellow_start:.4f}%, "
            f"{bright_yellow} {red_to_yellow_end:.4f}%, "
            f"{bright_yellow} {yellow_to_green_start:.4f}%, "
            f"{bright_green} {yellow_to_green_end:.4f}%, "
            f"{bright_green} {pos_999_before_pct:.4f}%, "
            f"{dark_green} {pos_999_pct:.4f}%, "
            f"{dark_green} 100%)"
        )

        tick_specs = [
            (0.0, format_num(global_min)),
            (pos_3_pct, "3"),
            (pos_5_pct, "5"),
            (100.0, format_num(global_max)),
        ]

    tick_specs = sorted(tick_specs, key=lambda x: x[0])
    deduped_ticks = []
    for left, label in tick_specs:
        if deduped_ticks and abs(left - deduped_ticks[-1][0]) < 0.2:
            continue
        deduped_ticks.append((left, label))

    tick_html = "\n".join(
        [
            "            "
            + f'<div class="legend-tick" style="left: {left:.4f}%;">'
            + '<span class="legend-tick-line"></span>'
            + f'<span class="legend-tick-label">{label}</span>'
            + "</div>"
            for left, label in deduped_ticks
        ]
    )

    return legend_gradient, tick_html

HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title}</title>
    <style>
        body {{
            margin: 0;
            font-family: Arial, sans-serif;
            background: #f2f4f8;
            color: #222;
        }}

        header {{
            padding: 20px 28px;
            background: white;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            position: sticky;
            top: 0;
            z-index: 10;
        }}

        header h1 {{
            margin: 0;
            font-size: 1.35rem;
            letter-spacing: -0.02em;
        }}

        header p {{
            margin: 8px 0 0;
            color: #555;
            max-width: 900px;
            line-height: 1.6;
        }}

        .grid {{
            display: grid;
            gap: 16px;
            padding: 20px;
            grid-template-columns: repeat(auto-fit, minmax(520px, 1fr));
            max-width: 1900px;
            margin: 0 auto 32px;
        }}

        .card {{
            background: white;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 10px 32px rgba(0,0,0,0.08);
            border: 1px solid rgba(0,0,0,0.06);
            display: flex;
            flex-direction: column;
        }}

        .card-header {{
            padding: 14px 18px;
            font-weight: 700;
            background: #fafbfc;
            border-bottom: 1px solid rgba(0,0,0,0.05);
        }}

        .card iframe {{
            width: 100%;
            height: {frame_height}px;
            border: {frame_border};
            flex: 1 1 auto;
        }}

        .single-map-card {{
            align-items: stretch;
        }}

        .slider-wrap {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 8px;
            width: 90%;
            margin: 14px auto 18px;
        }}

        .slider-wrap label {{
            width: 100%;
            text-align: center;
            font-weight: 600;
            color: #333;
        }}

        .penetration-slider {{
            width: 100%;
            max-width: 980px;
        }}

        .shared-legend {{
            margin: 20px auto 0;
            max-width: 920px;
            padding: 16px 26px;
            background: white;
            border-radius: 14px;
            box-shadow: 0 10px 24px rgba(0,0,0,0.08);
            border: 1px solid rgba(0,0,0,0.06);
            display: grid;
            gap: 12px;
        }}

        .legend-title {{
            font-weight: 700;
            color: #222;
            margin: 0;
        }}

        .legend-bar {{
            height: 18px;
            border-radius: 16px;
            background: {legend_gradient};
            border: 1px solid rgba(0,0,0,0.08);
        }}

        .legend-ticks {{
            position: relative;
            height: 22px;
            margin-top: 4px;
        }}

        .legend-tick {{
            position: absolute;
            transform: translateX(-50%);
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 3px;
        }}

        .legend-tick-line {{
            width: 0;
            height: 8px;
            border-left: 2px solid #333;
        }}

        .legend-tick-label {{
            color: #444;
            font-size: 0.85rem;
            font-weight: 600;
            line-height: 1;
        }}

        .legend-labels {{
            display: flex;
            justify-content: space-between;
            color: #555;
            font-size: 0.95rem;
        }}

        .legend-note {{
            color: #555;
            font-size: 0.95rem;
            line-height: 1.45;
        }}

        .footer {{
            text-align: center;
            padding: 16px 20px 24px;
            color: #666;
            font-size: 0.95rem;
        }}

        @media (max-width: 640px) {{
            header {{ padding: 14px 16px; }}
            .grid {{ padding: 14px; gap: 12px; }}
            .slider-wrap {{ width: 94%; margin: 12px auto 16px; }}
        }}

        @media (max-width: 1180px) {{
            .grid {{ grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); }}
        }}

        @media (max-width: 820px) {{
            .grid {{ grid-template-columns: minmax(280px, 1fr); }}
        }}
    </style>
</head>
<body>
    <header>
        <h1>{page_title}</h1>
    </header>

    <div class="shared-legend">
        <p class="legend-title">{legend_title}</p>
        <div class="legend-bar"></div>
        <div class="legend-ticks">
{legend_ticks}
        </div>
        <p class="legend-note">{legend_note}</p>
    </div>

    <section class="grid">
{cards_html}
    </section>

    <div class="footer">Keep all source map HTML files in the same directory as this viewer.</div>
    <script>
        const mapEntries = {map_entries_json};

        function updateMapCard(cardId, index) {{
            const entry = mapEntries[index];
            if (!entry) return;

            const titleEl = document.getElementById(`map-card-title-${{cardId}}`);
            const penetrationEl = document.getElementById(`penetration-value-${{cardId}}`);
            const frame = document.getElementById(`map-frame-${{cardId}}`);

            if (!titleEl || !penetrationEl || !frame) return;

            titleEl.textContent = entry.title;
            penetrationEl.textContent = `${{entry.penetration}}%`;
            frame.title = entry.title;

            if (frame.getAttribute('src') !== entry.file_path) {{
                frame.setAttribute('src', entry.file_path);
            }} else {{
                hideFrameColorbar(frame);
            }}
        }}

        function hideFrameColorbar(frame) {{
            try {{
                const doc = frame.contentDocument || frame.contentWindow.document;
                if (!doc) return;

                // Hide any Plotly colorbar containers and tighten the map frame.
                const colorbars = doc.querySelectorAll('[class*="colorbar"], .colorbar, .cbaxis, .cbaxis-title');
                colorbars.forEach(el => el.style.display = 'none');

                const titles = doc.querySelectorAll('g[aria-label="Colorbar"], .colorbar-title, .cbaxis-title');
                titles.forEach(el => el.style.display = 'none');
            }} catch (error) {{
                console.warn('Unable to hide embedded colorbar for', frame.src, error);
            }}
        }}

        function initializeMapCard(cardId) {{
            const slider = document.getElementById(`penetration-slider-${{cardId}}`);
            if (!slider) return;

            slider.addEventListener('input', event => {{
                updateMapCard(cardId, Number(event.target.value));
            }});
            updateMapCard(cardId, Number(slider.value));
        }}

{cards_init_script}
    </script>
</body>
</html>
'''

def discover_map_files(directory: Path):
    files = []

    map_files = sorted(directory.glob(f"{METRIC}_*.html"))

    map_order = [float(str(k.stem).split(f"_")[2]) for k in map_files]
    order_dict = dict(zip(map_order, map_files))
    order_dict1 = collections.OrderedDict(sorted(order_dict.items()))
    for num, file in order_dict1.items():

        files.append(file)

    return files


def create_grid_viewer(output_path, map_files, min_label, max_label, keyword, mode):
    keyword_upper = keyword.upper()
    metric_details = METRIC.split("_")
    if "NSCR" in metric_details[1]:
        metric_details[1] = "Normalized SCR (NSCR)"

    page_title = (
        f"Δ{metric_details[1]} Visualization (GFM - GFL): {metric_details[0]} analysis"
        if keyword_upper == "COMPARE"
        else f"{metric_details[1]} Visualization: {metric_details[0]} analysis"
    )

    legend_title = (
        f"Δ{metric_details[1]} Legend"
        if keyword_upper == "COMPARE"
        else f"{metric_details[1]} Legend"
    )
    legend_note = (
        f"*Yellow indicates no change in {metric_details[1]} from GFL to GFM"
        if keyword_upper == "COMPARE"
        else f"*Dark green indicates {metric_details[1]} value above 999 or no IBR located at bus"
    )

    # Build ordered map entries used by the slider-driven single card.
    map_entries = []
    for file_path in map_files:
        raw_title = os.path.splitext(file_path.name)[0]
        title_details = raw_title.split("_")
        display_title = (
            " ".join(title_details[:2]) + ": " + title_details[2] + "% IBRs"
            if keyword_upper == "CONTROL-NEUTRAL" or keyword_upper == "COMPARE"
            else " ".join(title_details[:2]) + ": " + title_details[2] + f"% {keyword} IBRs"
        )
        map_entries.append(
            {
                "title": display_title,
                "file_path": file_path.name,
                "penetration": title_details[2],
            }
        )

    slider_max = max(0, len(map_entries) - 1)

    if mode.lower() == "snapshot":
        initial_entry = map_entries[0]
        cards_html = """        <article class=\"card single-map-card\">\n            <div class=\"card-header\">{title}</div>\n            <iframe src=\"{file_path}\" title=\"{title}\" loading=\"lazy\" onload=\"hideFrameColorbar(this)\"></iframe>\n        </article>""".format(
            title=initial_entry["title"],
            file_path=initial_entry["file_path"],
        )
        cards_init_script = ""
    else:
        initial_indices = [
            0,
            slider_max // 2,
            slider_max,
        ]

        initial_entry_1 = map_entries[initial_indices[0]]
        initial_entry_2 = map_entries[initial_indices[1]]
        initial_entry_3 = map_entries[initial_indices[2]]

        cards_html = """        <article class=\"card single-map-card\">\n            <div class=\"card-header\" id=\"map-card-title-1\">{title_1}</div>\n            <iframe id=\"map-frame-1\" src=\"{file_1}\" title=\"{title_1}\" loading=\"lazy\" onload=\"hideFrameColorbar(this)\"></iframe>\n            <div class=\"slider-wrap\">\n                <label for=\"penetration-slider-1\">Penetration Level: <span id=\"penetration-value-1\">{pen_1}%</span></label>\n                <input id=\"penetration-slider-1\" class=\"penetration-slider\" type=\"range\" min=\"0\" max=\"{slider_max}\" step=\"1\" value=\"{idx_1}\" />\n            </div>\n        </article>\n\n        <article class=\"card single-map-card\">\n            <div class=\"card-header\" id=\"map-card-title-2\">{title_2}</div>\n            <iframe id=\"map-frame-2\" src=\"{file_2}\" title=\"{title_2}\" loading=\"lazy\" onload=\"hideFrameColorbar(this)\"></iframe>\n            <div class=\"slider-wrap\">\n                <label for=\"penetration-slider-2\">Penetration Level: <span id=\"penetration-value-2\">{pen_2}%</span></label>\n                <input id=\"penetration-slider-2\" class=\"penetration-slider\" type=\"range\" min=\"0\" max=\"{slider_max}\" step=\"1\" value=\"{idx_2}\" />\n            </div>\n        </article>\n\n        <article class=\"card single-map-card\">\n            <div class=\"card-header\" id=\"map-card-title-3\">{title_3}</div>\n            <iframe id=\"map-frame-3\" src=\"{file_3}\" title=\"{title_3}\" loading=\"lazy\" onload=\"hideFrameColorbar(this)\"></iframe>\n            <div class=\"slider-wrap\">\n                <label for=\"penetration-slider-3\">Penetration Level: <span id=\"penetration-value-3\">{pen_3}%</span></label>\n                <input id=\"penetration-slider-3\" class=\"penetration-slider\" type=\"range\" min=\"0\" max=\"{slider_max}\" step=\"1\" value=\"{idx_3}\" />\n            </div>\n        </article>""".format(
            title_1=initial_entry_1["title"],
            file_1=initial_entry_1["file_path"],
            pen_1=initial_entry_1["penetration"],
            idx_1=initial_indices[0],
            title_2=initial_entry_2["title"],
            file_2=initial_entry_2["file_path"],
            pen_2=initial_entry_2["penetration"],
            idx_2=initial_indices[1],
            title_3=initial_entry_3["title"],
            file_3=initial_entry_3["file_path"],
            pen_3=initial_entry_3["penetration"],
            idx_3=initial_indices[2],
            slider_max=slider_max,
        )
        cards_init_script = """        initializeMapCard(1);\n        initializeMapCard(2);\n        initializeMapCard(3);"""

    #build shared legend
    legend_gradient, legend_ticks = build_shared_legend(keyword, (min_label, max_label))

    html_content = HTML_TEMPLATE.format(
        page_title=page_title,
        frame_height=FRAME_HEIGHT_PX,
        frame_border=FRAME_BORDER,
        legend_gradient=legend_gradient,
        legend_ticks=legend_ticks,
        legend_title = legend_title,
        legend_note=legend_note,
        cards_html=cards_html,
        cards_init_script=cards_init_script,
        map_entries_json=json.dumps(map_entries),
        metric = METRIC,
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)


def get_global_metric_range(keyword_dir: Path, keyword: str, metric: str):
    excel_path = keyword_dir / f"Strength_Metric_Results_{metric}.xlsx"
    if not excel_path.exists():
        return None

    df = pd.read_excel(excel_path)
    return metric_global_range(
        df,
        METRIC,
        dynamic_cap_95=METRIC.startswith("dynamic_"),
        exclude_999_for_max=True,
    )


def main(keyword: str, analysis: str, mode: str, metric: str, case: str):
    global METRIC
    global OUTPUT_DIR
    OUTPUT_DIR = PROJECT_ROOT / f"output_{"_".join(Path(case).stem.split('_')[:2])}"

    METRIC = f"{analysis}_{metric}"

    keyword_dir = OUTPUT_DIR / f"{analysis}_analysis" / mode / keyword
    html_dir = keyword_dir / f"{metric}_htmls"
    html_dir.mkdir(parents=True, exist_ok=True)
    output_path = html_dir / f"Strength_All_Grid.html"
    map_files = discover_map_files(html_dir)

    if not map_files:
        print(html_dir)
        print(keyword)
        print("No individual strength metric map HTML files were found.")
        return

    strength_range = get_global_metric_range(keyword_dir, keyword, metric)

    if strength_range is None:
        min_label = f"Min {METRIC}"
        max_label = f"Max {METRIC}"
    else:
        if keyword.upper() == "COMPARE":
            min_label = str(-1*strength_range[1]) if float(strength_range[0]) > 0 else format_num(strength_range[0])
        else:
            min_label = "0" if float(strength_range[0]) > 3 else format_num(strength_range[0])
        max_label = format_num(strength_range[1])

    create_grid_viewer(output_path, map_files, min_label, max_label, keyword, mode)
    print(f"Generated grid viewer: {output_path}")
    print(f"Included {len(map_files)} maps")
    for f in map_files:
        print(f" - {f.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build combined HTML viewer for generated maps.")
    parser.add_argument("--keyword", required=True, choices=["GFL", "GFM", "COMPARE", "CONTROL-NEUTRAL"])
    parser.add_argument("--analysis", default="static", choices=["static", "dynamic"])
    parser.add_argument("--mode", default="evolution", choices=["snapshot", "evolution"])
    parser.add_argument("--metric", default="SCR", help="Strength metric type to evaluate (e.g., SCR)")
    parser.add_argument("--case-file", required=True, help="Case file path")
    args = parser.parse_args()
    main(
        args.keyword,
        args.analysis,
        args.mode,
        args.metric,
        args.case_file,
    )
