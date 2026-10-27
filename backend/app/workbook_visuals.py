"""Lightweight chart and merge metadata for saved workbook previews."""

from functools import lru_cache
from math import isfinite
from pathlib import Path
from posixpath import basename, dirname, join, normpath
from zipfile import ZipFile

from defusedxml.ElementTree import fromstring, iterparse
from openpyxl.utils.cell import range_boundaries


CHART = "http://schemas.openxmlformats.org/drawingml/2006/chart"
DRAWING = "http://schemas.openxmlformats.org/drawingml/2006/main"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MAX_DRAWING_XML = 2 * 1024 * 1024
MAX_CHART_POINTS = 1000


def _resolve(source, target):
    path = normpath(join(dirname(source), target)) if not target.startswith("/") else target.lstrip("/")
    return path if path.startswith("xl/") and ".." not in path.split("/") else None


def _relationships(archive, source):
    name = join(dirname(source), "_rels", basename(source) + ".rels")
    if name not in archive.namelist() or archive.getinfo(name).file_size > MAX_DRAWING_XML:
        return {}
    root = fromstring(archive.read(name))
    return {
        item.get("Id"): _resolve(source, item.get("Target", ""))
        for item in root.findall(f"{{{REL}}}Relationship")
    }


def _points(parent, cache_type):
    if parent is None:
        return {}, False
    cache = parent.find(f".//{{{CHART}}}{cache_type}")
    if cache is None:
        return {}, False
    count = cache.find(f"{{{CHART}}}ptCount")
    truncated = count is not None and int(count.get("val", "0")) > MAX_CHART_POINTS
    points = {}
    for item in cache.findall(f"{{{CHART}}}pt"):
        try:
            index = int(item.get("idx", ""))
        except ValueError:
            continue
        if 0 <= index < MAX_CHART_POINTS:
            value = item.findtext(f"{{{CHART}}}v")
            if value is not None:
                points[index] = value
    return points, truncated


def _chart(archive, path):
    if path not in archive.namelist() or archive.getinfo(path).file_size > MAX_DRAWING_XML:
        return None
    root = fromstring(archive.read(path))
    chart = root.find(f"{{{CHART}}}chart")
    if chart is None:
        return None
    title = " ".join(
        element.text or "" for element in chart.findall(f".//{{{CHART}}}title//{{{DRAWING}}}t")
    ).strip()
    plot = chart.find(f"{{{CHART}}}plotArea")
    if plot is None:
        return None
    visual = None
    kind = ""
    for candidate in ("bar", "line", "area", "pie"):
        visual = plot.find(f"{{{CHART}}}{candidate}Chart")
        if visual is not None:
            kind = candidate
            break
    if visual is None:
        return None
    if kind == "bar":
        direction = visual.find(f"{{{CHART}}}barDir")
        kind = "bar" if direction is not None and direction.get("val") == "bar" else "column"
    series = []
    categories = []
    truncated = False
    for item in visual.findall(f"{{{CHART}}}ser"):
        label = item.findtext(f".//{{{CHART}}}tx//{{{CHART}}}v") or f"Seria {len(series) + 1}"
        category_node = item.find(f"{{{CHART}}}cat")
        category_values, category_truncated = _points(category_node, "strCache")
        if not category_values:
            category_values, category_truncated = _points(category_node, "numCache")
        values, value_truncated = _points(item.find(f"{{{CHART}}}val"), "numCache")
        if not values:
            continue
        point_count = min(MAX_CHART_POINTS, max(values) + 1)
        if not categories:
            categories = [category_values.get(i, str(i + 1)) for i in range(point_count)]
        numbers = []
        for index in range(point_count):
            try:
                number = float(values[index]) if index in values else None
            except ValueError:
                number = None
            numbers.append(number if number is not None and isfinite(number) else None)
        series.append({"name": label, "values": numbers})
        truncated = truncated or category_truncated or value_truncated
    if not series:
        return None
    return {
        "title": title or "Grafik",
        "type": kind,
        "categories": categories,
        "series": series,
        "truncated": truncated,
    }


@lru_cache(maxsize=24)
def sheet_visuals(path_string, modified_ns, sheet_index):
    """Cache metadata by file revision; chart values come from the XLSX caches."""
    del modified_ns
    worksheet = f"xl/worksheets/sheet{sheet_index + 1}.xml"
    merges = []
    charts = []
    with ZipFile(Path(path_string)) as archive:
        if worksheet in archive.namelist():
            with archive.open(worksheet) as stream:
                events = iterparse(stream, events=("start", "end"))
                _, root = next(events)
                for event, element in events:
                    if event != "end":
                        continue
                    if element.tag.endswith("}mergeCell"):
                        try:
                            merges.append(range_boundaries(element.get("ref", "")))
                        except ValueError:
                            pass
                    if element.tag.endswith("}row") or element.tag.endswith("}mergeCell"):
                        root.clear()
        for drawing in _relationships(archive, worksheet).values():
            if not drawing or "/drawings/" not in drawing or drawing not in archive.namelist():
                continue
            if archive.getinfo(drawing).file_size > MAX_DRAWING_XML:
                continue
            drawing_xml = fromstring(archive.read(drawing))
            chart_relations = _relationships(archive, drawing)
            for element in drawing_xml.findall(f".//{{{CHART}}}chart"):
                chart_path = chart_relations.get(element.get(f"{{{OFFICE_REL}}}id"))
                if chart_path:
                    parsed = _chart(archive, chart_path)
                    if parsed:
                        charts.append(parsed)
    return merges, charts
