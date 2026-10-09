"""Execute only the module-level import statements of contract-file.py and report
whether pmpe.support_package (or support_package_cmd) gets loaded."""
import ast, sys
src_path = sys.argv[1]
tree = ast.parse(open(src_path).read())
imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
code = compile(ast.Module(body=imports, type_ignores=[]), src_path, "exec")
exec(code, {"__name__": "contract_file_imports"})
loaded = sorted(m for m in sys.modules if m.startswith("pmpe"))
print("module-level import statements executed:", len(imports))
print("pmpe modules loaded:", len(loaded))
print("pmpe.support_package loaded:", "pmpe.support_package" in sys.modules)
print("pmpe.cli.support_package_cmd loaded:", "pmpe.cli.support_package_cmd" in sys.modules)
