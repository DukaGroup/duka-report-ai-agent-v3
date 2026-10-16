"""Model-authored calculations over supplied data only, executed in an isolated worker."""

import ast
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, Inexact, ROUND_HALF_EVEN, localcontext


def number(value):
    if value is None or isinstance(value, bool):
        raise ValueError("number() needs a finite numeric value; handle missing values explicitly.")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("number() needs a finite numeric value.") from None
    if not result.is_finite() or abs(result.adjusted()) > 100:
        raise ValueError("Calculation numbers must be finite and within 100 decimal places of magnitude.")
    return result


def date_of(value):
    """Normalize ISO or SAP YYYYMMDD dates; missing/zero dates remain missing."""
    if value in (None, "", "00000000"):
        return None
    text = str(value)
    if "T" in text or " " in text:
        return datetime.fromisoformat(text).date().isoformat()
    return date.fromisoformat(text).isoformat()


def divide(left, right, places):
    if not isinstance(places, int) or isinstance(places, bool) or not 0 <= places <= 12:
        raise ValueError("divide() requires 0–12 decimal places.")
    with localcontext() as context:
        context.prec = 80
        context.traps[Inexact] = False
        return (number(left) / number(right)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN)


def require(condition):
    if not condition:
        raise ValueError("A model-authored data integrity check failed.")


BUILTINS = {"len": len, "range": range, "enumerate": enumerate, "zip": zip, "str": str, "int": int,
            "round": round, "abs": abs, "min": min, "max": max, "sum": sum, "sorted": sorted,
            "list": list, "tuple": tuple, "dict": dict, "set": set, "bool": bool,
            "any": any, "all": all, "number": number, "date_of": date_of, "divide": divide, "require": require}
METHODS = {"get", "items", "keys", "values", "append", "extend", "setdefault", "add",
           "strip", "upper", "lower", "casefold", "startswith", "endswith", "replace"}
NODES = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Expr, ast.Call, ast.Name, ast.Load, ast.Store,
         ast.Attribute, ast.Constant, ast.keyword, ast.Assign, ast.AugAssign, ast.Return, ast.For, ast.If,
         ast.IfExp, ast.Compare, ast.BoolOp, ast.UnaryOp, ast.BinOp, ast.List, ast.Tuple, ast.Dict, ast.Set,
         ast.Subscript, ast.Slice, ast.JoinedStr, ast.FormattedValue, ast.Pass, ast.Break, ast.Continue,
         ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp, ast.comprehension,
         ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.USub, ast.UAdd, ast.Not,
         ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot)


def validate_script(source):
    if not isinstance(source, str) or not source.strip() or len(source.encode()) > 65536:
        raise ValueError("Calculation must define calculate(tables), within 64 KB.")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"Calculation syntax error at line {exc.lineno}.") from None
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef) or tree.body[0].name != "calculate":
        raise ValueError("Define only def calculate(tables).")
    f = tree.body[0]
    if (f.decorator_list or f.returns or f.args.defaults or f.args.kw_defaults or f.args.posonlyargs
            or f.args.kwonlyargs or f.args.vararg or f.args.kwarg or len(f.args.args) != 1
            or f.args.args[0].arg != "tables" or f.args.args[0].annotation or f.type_params):
        raise ValueError("Use the signature calculate(tables), without annotations or decorators.")
    nodes = list(ast.walk(tree))
    if len(nodes) > 10000:
        raise ValueError("Calculation exceeds the expression complexity limit.")
    protected = {*BUILTINS, "calculate", "tables"}
    for node in nodes:
        line = getattr(node, "lineno", 1)
        if not isinstance(node, NODES) or isinstance(node, ast.FunctionDef) and node is not f:
            raise ValueError(f"Calculation operation {type(node).__name__} is not allowed at line {line}.")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError(f"Private names are not allowed at line {line}.")
        if isinstance(node, ast.Attribute) and (node.attr not in METHODS or not isinstance(node.ctx, ast.Load)):
            raise ValueError(f"Unsupported calculation method at line {line}.")
        if isinstance(node, ast.Call):
            if not (isinstance(node.func, ast.Name) and node.func.id in BUILTINS
                    or isinstance(node.func, ast.Attribute) and node.func.attr in METHODS):
                raise ValueError(f"Use documented calculation helpers at line {line}.")
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in protected:
            raise ValueError(f"Cannot replace calculation helpers at line {line}.")
        if isinstance(node, ast.Constant) and isinstance(node.value, (float, complex)):
            raise ValueError(f"Use number('0.10') for decimal literals at line {line}.")
    return compile(tree, "<calculation>", "exec")


def run_script(source, tables):
    code = validate_script(source)
    namespace = {"__builtins__": BUILTINS}
    exec(code, namespace)
    with localcontext() as context:
        context.prec = 80
        # Rounded arithmetic is never silently accepted as exact financial output.
        context.traps[Inexact] = True
        return namespace["calculate"](tables)
