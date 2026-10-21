"""Restricted generated Python, with report helpers instead of raw library access."""

import ast
import json
from itertools import chain

from .currencies import currency_fields, display_currency
from .workbooks import ReportDataError, analysis_data

METHODS = {"sheet", "title", "paragraph", "heading", "metric", "compare", "table", "chart", "space", "widths",
           "default_layout", "currencies", "columns", "analysis_count", "narrative", "reference_table"}
BUILTINS = {"len": len, "range": range, "enumerate": enumerate, "zip": zip, "str": str, "int": int,
            "float": float, "round": round, "abs": abs, "min": min, "max": max, "sum": sum,
            "sorted": sorted, "list": list, "tuple": tuple, "dict": dict, "bool": bool}
NODES = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Expr, ast.Call, ast.Name, ast.Load, ast.Store,
         ast.Attribute, ast.Constant, ast.keyword, ast.Assign, ast.AugAssign, ast.Return, ast.For, ast.If,
         ast.Compare, ast.BoolOp, ast.UnaryOp, ast.BinOp, ast.List, ast.Tuple, ast.Dict, ast.Subscript, ast.Slice,
         ast.JoinedStr, ast.FormattedValue, ast.Pass, ast.Break, ast.Continue,
         ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.USub, ast.UAdd, ast.Not,
         ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot)


def validate_script(source):
    if not isinstance(source, str) or not source.strip() or len(source.encode()) > 65536:
        raise ReportDataError("Workbook script is missing or exceeds the 64 KB limit.")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ReportDataError(f"Workbook script syntax error at line {exc.lineno}.") from None
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef) or tree.body[0].name != "build":
        raise ReportDataError("Workbook script must define only build(report).")
    function = tree.body[0]
    if (function.decorator_list or function.returns or function.args.defaults or function.args.kw_defaults
            or function.args.posonlyargs or function.args.kwonlyargs or function.args.vararg or function.args.kwarg
            or len(function.args.args) != 1 or function.args.args[0].arg != "report" or function.args.args[0].annotation):
        raise ReportDataError("Workbook script must use the signature build(report).")
    nodes = list(ast.walk(tree))
    if len(nodes) > 10000:
        raise ReportDataError("Workbook script is too complex.")
    for node in nodes:
        if not isinstance(node, NODES) or isinstance(node, ast.FunctionDef) and node is not function:
            raise ReportDataError(f"Workbook script operation {type(node).__name__} is not allowed at line {getattr(node, 'lineno', 1)}.")
        if isinstance(node, ast.Name) and (node.id.startswith("_") or node.id in {"eval", "exec", "open", "getattr", "setattr", "globals", "locals", "vars", "type", "object", "compile", "input", "help", "exit", "quit", "print"}):
            raise ReportDataError(f"Workbook script name is not allowed at line {node.lineno}.")
        if isinstance(node, ast.Attribute) and node.attr not in METHODS:
            raise ReportDataError(f"Workbook script attribute is not an approved report helper at line {node.lineno}.")
        if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, ast.Store):
            raise ReportDataError("Workbook scripts cannot modify report helpers or source objects.")
        if isinstance(node, ast.For) and (not isinstance(node.target, ast.Name) or node.target.id in {*BUILTINS, "report", "build"}):
            raise ReportDataError("Workbook loops must use an ordinary local variable.")
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(not isinstance(target, ast.Name) or target.id in {*BUILTINS, "report", "build"} for target in targets):
                raise ReportDataError("Workbook scripts may assign local variable names only.")
    return compile(tree, "<workbook-script>", "exec")


class ReportLayout:
    def __init__(self, document, snapshot):
        self._document, self._datasets = document, analysis_data(snapshot)
        self._sheets, self._commands, self._default = [], 0, False
        self._reference = json.loads(snapshot["provenance_json"]).get("format_reference", {})

    def default_layout(self):
        if self._sheets:
            raise ReportDataError("Choose a custom layout or default_layout, not both.")
        self._default = True

    def sheet(self, name):
        from .balance_reconciliation import CUTOFF_SHEET_NAMES, SHEET_NAMES
        reserved = {n.casefold() for pair in SHEET_NAMES.values() for n in pair} | {
            n.casefold() for n in CUTOFF_SHEET_NAMES.values()
        }
        if isinstance(name,str) and name.casefold() in reserved:
            raise ReportDataError("Balance sheet names are reserved for the backend.")
        if self._default or len(self._sheets) >= 8 or not isinstance(name, str) or not name.strip() or len(name) > 31:
            raise ReportDataError("Workbook layout supports up to eight named output sheets, each at most 31 characters.")
        sheet = LayoutSheet(self, name)
        self._sheets.append(sheet)
        return sheet

    def analysis_count(self):
        return len(self._datasets)

    def columns(self, dataset):
        data = self._dataset(dataset)
        return list(dict.fromkeys(chain((c["name"] for c in data.get("columns", [])), (k for row in data["rows"] for k in row))))

    def currencies(self, dataset, currency_column=None):
        data = self._dataset(dataset)
        fields = currency_fields(data["rows"], data.get("columns", []), data.get("query"))
        if currency_column is not None and currency_column not in fields:
            raise ReportDataError("Currency dimension is not a source currency field.")
        if currency_column is None and len(fields) > 1:
            raise ReportDataError("Choose an explicit currency_column when multiple currency fields exist.")
        field = currency_column or next(iter(fields), None)
        return sorted({str(display_currency(row.get(field))) for row in data["rows"]}) if field else ["ALL"]

    def _dataset(self, index):
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(self._datasets):
            raise ReportDataError("Workbook dataset index is unavailable.")
        return self._datasets[index]

    def _export(self):
        if self._default:
            if any(len(profile["headers"])>1 and any(len(profile["column_widths"])==len(self.columns(index)) for index in range(self.analysis_count()))
                   for profile in self._reference.get("sheet_layouts", [])):
                raise ReportDataError("The selected grouped reference requires a custom layout using s.reference_table; default_layout would flatten it.")
            return None
        if not self._sheets or not any(sheet._items for sheet in self._sheets):
            raise ReportDataError("Workbook script produced no output sheets.")
        items = [item for sheet in self._sheets for item in sheet._items]
        referenced = {item["dataset"] for item in items if item["kind"] == "reference_table"}
        for item in items:
            if item["kind"] == "table" and item["dataset"] not in referenced:
                fields = item.get("columns") or self.columns(item["dataset"])
                if any(len(profile["headers"])>1 and len(profile["column_widths"])==len(fields)
                       for profile in self._reference.get("sheet_layouts", [])):
                    raise ReportDataError("A compatible grouped format reference is selected. Use s.reference_table with authored current-period headers instead of flattening it into s.table.")
        return [{"name": sheet._name, "items": sheet._items, "widths": sheet._widths} for sheet in self._sheets]


class LayoutSheet:
    def __init__(self, report, name):
        self._report, self._name, self._items, self._widths = report, name, [], [38, 24, 22, 22, 22, 22, 22, 22]

    def _add(self, kind, **options):
        self._report._commands += 1
        if self._report._commands > 2000:
            raise ReportDataError("Workbook script exceeded the layout command limit.")
        self._items.append({"kind": kind, **options})

    def title(self, text=None):
        self._add("title", text=self._report._document["title"] if text is None else str(text))

    def paragraph(self, text=None):
        self._add("paragraph", text=self._report._document["summary"] if text is None else str(text))

    def heading(self, text):
        self._add("heading", text=str(text))

    def narrative(self):
        self.paragraph()
        for section in self._report._document["sections"]:
            self.heading(section["heading"])
            self.paragraph(section["body"])
        for metric in self._report._document["metrics"]:
            self.paragraph(f"{metric['label']}: {metric['value']} — {metric['explanation']}")
        for limitation in self._report._document["limitations"]:
            self.paragraph(limitation)

    def space(self, rows=1):
        if isinstance(rows, bool) or not isinstance(rows, int) or not 0 <= rows <= 20:
            raise ReportDataError("Layout spacing must be 0–20 rows.")
        self._add("space", rows=rows)

    def widths(self, values):
        if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 100 or any(not isinstance(v, (int, float)) or not 8 <= v <= 60 for v in values):
            raise ReportDataError("Column widths must be 8–60 characters for 1–100 columns.")
        self._widths = list(values)

    def metric(self, dataset, column, label, currency=None, operation="sum", currency_column=None):
        self._report._dataset(dataset)
        self._add("metric", dataset=dataset, column=column, label=str(label), currency=currency, operation=operation, currency_column=currency_column)

    def compare(self, left_dataset, left_column, right_dataset, right_column, label, currency=None, operation="difference", currency_column=None):
        self._report._dataset(left_dataset)
        self._report._dataset(right_dataset)
        self._add("compare", left_dataset=left_dataset, left_column=left_column, right_dataset=right_dataset, right_column=right_column,
                  label=str(label), currency=currency, operation=operation, currency_column=currency_column)

    def table(self, dataset, columns=None, currency=None, currency_column=None, formats=None):
        self._report._dataset(dataset)
        self._add("table", dataset=dataset, columns=columns, currency=currency, currency_column=currency_column, formats=formats)

    def reference_table(self, dataset, reference_sheet, headers, columns=None, formats=None):
        self._report._dataset(dataset)
        self._add("reference_table", dataset=dataset, reference_sheet=str(reference_sheet), headers=headers,
                  columns=columns, formats=formats)

    def chart(self, dataset, category, measures, title, chart_type="column", currency=None, currency_column=None):
        self._report._dataset(dataset)
        self._add("chart", dataset=dataset, category=category, measures=measures, title=str(title), chart_type=chart_type,
                  currency=currency, currency_column=currency_column)


def run_script(source, document, snapshot):
    code = validate_script(source)
    report = ReportLayout(document, snapshot)
    namespace = {"__builtins__": BUILTINS}
    exec(code, namespace)
    namespace["build"](report)
    return report._export()
