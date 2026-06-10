from tree_sitter import Language, Parser
import tree_sitter_python as tspython
import tree_sitter_java as tsjava
import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript
import tree_sitter_go as tsgo
import tree_sitter_rust as tsrust

from codeengine.models.search_models import Symbol, FunctionResult

LANG_MAP = {
    ".py":   "python",
    ".java": "java",
    ".js":   "javascript",
    ".ts":   "typescript",
    ".go":   "go",
    ".rs":   "rust",
}

PARSERS = {
    "python":     Parser(Language(tspython.language())),
    "java":       Parser(Language(tsjava.language())),
    "javascript": Parser(Language(tsjavascript.language())),
    "typescript": Parser(Language(tstypescript.language_typescript())),
    "go":         Parser(Language(tsgo.language())),
    "rust":       Parser(Language(tsrust.language())),
}

NODE_TYPES = {
    "python": {
        "function_definition": "function",
        "lambda": "function",
        "class_definition": "class"
    },
    "java": {
        "method_declaration": "method",
        "lambda_expression": "function",
        "class_declaration": "class"
    },
    "javascript": {
        "function_declaration": "function",
        "arrow_function": "function",
        "function_expression": "function",
        "generator_function": "function",
        "generator_function_declaration": "function",
        "class_declaration": "class"
    },
    "typescript": {
        "function_declaration": "function",
        "arrow_function": "function",
        "function_expression": "function",
        "generator_function": "function",
        "generator_function_declaration": "function",
        "method_definition": "method",
        "class_declaration": "class"
    },
    "go": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_declaration": "class"
    },
    "rust": {
        "function_item": "function",
        "closure_expression": "function",
        "impl_item": "class",
        "struct_item": "class"
    }
}

IMPORT_NODE_TYPES = {
    "python": {"import_statement", "import_from_statement"},
    "java": {"import_declaration"},
    "javascript": {"import_statement"},
    "typescript": {"import_statement"},
    "go": {"import_declaration", "import_spec"},
    "rust": {"use_declaration"}
}

def detect_language(file_path: str) -> str | None:
    """Return language string from LANG_MAP based on file extension. Return None if unknown."""
    from pathlib import Path
    ext = Path(file_path).suffix.lower()
    return LANG_MAP.get(ext)

def _extract_name(node) -> str | None:
    """Extract name identifier from different AST node types."""
    name_node = node.child_by_field_name("name")
    if name_node:
        return name_node.text.decode(errors="replace")
        
    # Fallback for specific Go types
    if node.type == "type_declaration":
        for child in node.children:
            if child.type == "type_spec":
                spec_name = child.child_by_field_name("name")
                if spec_name:
                    return spec_name.text.decode(errors="replace")
                    
    # Fallback for JS/TS/Python/Java/Rust arrow functions, lambdas, closures, expressions assigned to variables
    if node.type in ("arrow_function", "function_expression", "generator_function", "lambda", "lambda_expression", "closure_expression"):
        p = node.parent
        while p:
            if p.type == "variable_declarator":
                var_name = p.child_by_field_name("name")
                if var_name:
                    return var_name.text.decode(errors="replace")
            elif p.type == "assignment":
                left_node = p.child_by_field_name("left")
                if left_node:
                    return left_node.text.decode(errors="replace")
            elif p.type == "local_variable_declaration":
                # Check children for a variable_declarator
                for child in p.children:
                    if child.type == "variable_declarator":
                        var_name = child.child_by_field_name("name")
                        if var_name:
                            return var_name.text.decode(errors="replace")
            elif p.type == "let_declaration":
                pattern_node = p.child_by_field_name("pattern")
                if pattern_node:
                    return pattern_node.text.decode(errors="replace")
            p = p.parent
            
    # Fallback for Rust impl blocks
    if node.type == "impl_item":
        type_node = node.child_by_field_name("type")
        if type_node:
            return type_node.text.decode(errors="replace")
            
    return None

def parse_file(path: str) -> list[Symbol]:
    """
    Read file bytes. Detect language. Get parser from PARSERS dict.
    Walk root_node recursively to extract functions, classes, methods.
    """
    lang = detect_language(path)
    if not lang or lang not in PARSERS:
        return []
        
    try:
        with open(path, "rb") as f:
            source_bytes = f.read()
    except Exception:
        return []
        
    parser = PARSERS[lang]
    # Re-instantiate Parser to avoid sharing parsed state in concurrent files
    # but reuse the loaded Language binding
    local_parser = Parser(parser.language)
    tree = local_parser.parse(source_bytes)
    
    symbols = []
    node_types = NODE_TYPES.get(lang, {})
    
    def walk(node):
        if node.type in node_types:
            name = _extract_name(node)
            if name:
                kind = node_types[node.type]
                line_start = node.start_point[0] + 1
                line_end = node.end_point[0] + 1
                symbols.append(Symbol(
                    name=name,
                    kind=kind,
                    file="",  # caller fills it
                    line_start=line_start,
                    line_end=line_end
                ))
        for child in node.children:
            walk(child)
            
    walk(tree.root_node)
    return symbols

def parse_code_string(source_code: str, file_path_hint: str | None = None, lang_hint: str | None = None) -> list[Symbol]:
    """
    Parse a snippet of code (not loaded from a file path).
    Attempts to identify language from:
    1. lang_hint if provided
    2. file_path_hint if provided
    3. guessing basic syntax keywords
    """
    lang = None
    if lang_hint:
        lang = lang_hint
    elif file_path_hint:
        lang = detect_language(file_path_hint)
        
    if not lang:
        # Simple heuristic guess based on common keywords
        content_bytes = source_code.encode("utf-8", errors="replace")
        if b"fn " in content_bytes and (b"impl " in content_bytes or b"pub " in content_bytes):
            lang = "rust"
        elif b"func " in content_bytes:
            lang = "go"
        elif b"def " in content_bytes or (b"import " in content_bytes and b":" in content_bytes):
            lang = "python"
        elif b"class " in content_bytes and (b"public " in content_bytes or b"private " in content_bytes or b"void " in content_bytes):
            lang = "java"
        elif b"const " in content_bytes or b"let " in content_bytes or b"function " in content_bytes or b"async " in content_bytes or b"=>" in content_bytes:
            lang = "javascript"
        else:
            lang = "python"

    if lang not in PARSERS:
        lang = "python"

    try:
        source_bytes = source_code.encode("utf-8", errors="replace")
    except Exception:
        return []

    parser = PARSERS[lang]
    local_parser = Parser(parser.language)
    tree = local_parser.parse(source_bytes)
    
    symbols = []
    node_types = NODE_TYPES.get(lang, {})
    
    def walk(node):
        if node.type in node_types:
            name = _extract_name(node)
            if name:
                kind = node_types[node.type]
                line_start = node.start_point[0] + 1
                line_end = node.end_point[0] + 1
                symbols.append(Symbol(
                    name=name,
                    kind=kind,
                    file="",
                    line_start=line_start,
                    line_end=line_end
                ))
        for child in node.children:
            walk(child)
            
    walk(tree.root_node)
    return symbols

# Per-language node type categories for the block-level editor
BLOCK_FUNCTION_TYPES = {
    "python":     {"function_definition", "decorated_definition"},
    "javascript": {"function_declaration", "generator_function_declaration",
                   "lexical_declaration", "variable_declaration"},  # for const/let fn
    "typescript": {"function_declaration", "generator_function_declaration",
                   "lexical_declaration", "variable_declaration",
                   "ambient_declaration"},
    "java":       {"method_declaration", "constructor_declaration"},
    "go":         {"function_declaration", "method_declaration"},
    "rust":       {"function_item"},
}
BLOCK_CLASS_TYPES = {
    "python":     {"class_definition"},
    "javascript": {"class_declaration"},
    "typescript": {"class_declaration", "abstract_class_declaration"},
    "java":       {"class_declaration", "interface_declaration", "enum_declaration"},
    "go":         {"type_declaration"},
    "rust":       {"struct_item", "impl_item", "trait_item", "enum_item"},
}
BLOCK_IMPORT_TYPES = {
    "python":     {"import_statement", "import_from_statement"},
    "javascript": {"import_statement"},
    "typescript": {"import_statement"},
    "java":       {"import_declaration"},
    "go":         {"import_declaration"},
    "rust":       {"use_declaration"},
}

def _is_constant_node(node, lang: str) -> bool:
    """Return True if the node looks like a module-level constant."""
    if lang == "python":
        # assignment where the first target name is ALL_CAPS
        if node.type == "expression_statement":
            inner = node.children[0] if node.children else None
            if inner and inner.type == "assignment":
                left = inner.child_by_field_name("left")
                if left and left.text:
                    name = left.text.decode(errors="replace").strip()
                    return name.isupper() and name.isidentifier()
        if node.type == "assignment":
            left = node.child_by_field_name("left")
            if left and left.text:
                name = left.text.decode(errors="replace").strip()
                return name.isupper() and name.isidentifier()
    # JS/TS: const UPPER = ...
    if lang in ("javascript", "typescript"):
        if node.type in ("lexical_declaration", "variable_declaration"):
            for child in node.children:
                if child.type == "variable_declarator":
                    vname = child.child_by_field_name("name")
                    if vname and vname.text:
                        n = vname.text.decode(errors="replace").strip()
                        if n.isupper() and n.isidentifier():
                            return True
    return False

def _node_top_name(node, lang: str) -> str | None:
    """Extract a best-effort name for a top-level node."""
    # Try tree-sitter field 'name'
    name_node = node.child_by_field_name("name")
    if name_node and name_node.text:
        return name_node.text.decode(errors="replace").strip()
    # JS/TS lexical_declaration: const foo = () => ...
    if lang in ("javascript", "typescript"):
        for child in node.children:
            if child.type == "variable_declarator":
                vn = child.child_by_field_name("name")
                if vn:
                    return vn.text.decode(errors="replace").strip()
    # Go type_declaration → first type_spec
    if node.type == "type_declaration":
        for child in node.children:
            if child.type == "type_spec":
                vn = child.child_by_field_name("name")
                if vn:
                    return vn.text.decode(errors="replace").strip()
    # Rust impl_item: impl TypeName
    if node.type == "impl_item":
        type_node = node.child_by_field_name("type")
        if type_node:
            return type_node.text.decode(errors="replace").strip()
    # Python expression_statement wrapping an assignment (e.g. MAX = 100)
    if node.type == "expression_statement" and node.children:
        inner = node.children[0]
        if inner.type == "assignment":
            left = inner.child_by_field_name("left")
            if left and left.text:
                return left.text.decode(errors="replace").strip()
    return None

def parse_blocks_from_code(
    source_code: str,
    file_path_hint: str | None = None,
    lang_hint: str | None = None,
) -> list[tuple[str, str | None, str]]:
    """
    Parse top-level code blocks from a multi-block source string.

    Supports Python, JavaScript, TypeScript, Java, Go, Rust via tree-sitter.
    Falls back gracefully to the Python ast module for Python when tree-sitter
    parsing yields no useful blocks.

    Returns:
        list of (kind, name, source_text) tuples where kind is one of:
        "function" | "class" | "import" | "constant" | "other"
    """
    # Detect if we have separators in the code
    import re
    separator_pat = re.compile(r"^\s*[-=]{5,}\s*$")
    
    # Check if any line matches separator
    has_separator = False
    for line in source_code.splitlines():
        if separator_pat.match(line):
            has_separator = True
            break

    if has_separator:
        chunks = []
        current_chunk = []
        for line in source_code.splitlines(keepends=True):
            if separator_pat.match(line):
                if current_chunk:
                    chunks.append("".join(current_chunk))
                    current_chunk = []
            else:
                current_chunk.append(line)
        if current_chunk:
            chunks.append("".join(current_chunk))

        all_blocks = []
        for chunk in chunks:
            if chunk.strip():
                all_blocks.extend(parse_blocks_from_code(chunk, file_path_hint, lang_hint))
        return all_blocks

    # Detect language
    lang = lang_hint
    if not lang and file_path_hint:
        lang = detect_language(file_path_hint)
    if not lang:
        src = source_code.encode("utf-8", errors="replace")
        if b"fn " in src and (b"impl " in src or b"pub " in src):
            lang = "rust"
        elif b"func " in src:
            lang = "go"
        elif b"def " in src or (b"import " in src and b":" in src):
            lang = "python"
        elif b"class " in src and (b"public " in src or b"private " in src or b"void " in src):
            lang = "java"
        elif b"const " in src or b"let " in src or b"function " in src or b"=>" in src:
            lang = "javascript"
        else:
            lang = "python"

    if lang not in PARSERS:
        lang = "python"

    source_bytes = source_code.encode("utf-8", errors="replace")
    parser = PARSERS[lang]
    local_parser = Parser(parser.language)
    tree = local_parser.parse(source_bytes)

    lines = source_code.splitlines(keepends=True)
    blocks: list[tuple[str, str | None, str]] = []

    fn_types  = BLOCK_FUNCTION_TYPES.get(lang, set())
    cls_types = BLOCK_CLASS_TYPES.get(lang, set())
    imp_types = BLOCK_IMPORT_TYPES.get(lang, set())

    for node in tree.root_node.children:
        if node.is_named is False:
            continue  # skip punctuation / whitespace tokens

        start = node.start_point[0]      # 0-indexed line
        end   = node.end_point[0] + 1    # exclusive
        src   = "".join(lines[start:end])

        if not src.strip():
            continue

        name: str | None = None

        if node.type in imp_types:
            blocks.append(("import", None, src))

        elif node.type in fn_types:
            # Could be a constant-assigned arrow/lambda — check first
            if _is_constant_node(node, lang):
                name = _node_top_name(node, lang)
                blocks.append(("constant", name, src))
            else:
                name = _node_top_name(node, lang)
                blocks.append(("function", name, src))

        elif node.type in cls_types:
            name = _node_top_name(node, lang)
            blocks.append(("class", name, src))

        elif _is_constant_node(node, lang):
            name = _node_top_name(node, lang)
            blocks.append(("constant", name, src))

        else:
            # Python decorated_definition wraps a def/class
            if node.type == "decorated_definition" and lang == "python":
                inner = node.children[-1] if node.children else None
                if inner and inner.type in ("function_definition", "async_function_definition"):
                    name = _node_top_name(inner, lang)
                    blocks.append(("function", name, src))
                elif inner and inner.type == "class_definition":
                    name = _node_top_name(inner, lang)
                    blocks.append(("class", name, src))
                else:
                    blocks.append(("other", None, src))
            else:
                blocks.append(("other", None, src))

    return blocks


def find_symbol_bounds_in_code(
    code: str,
    name: str,
    kind: str,
    file_path_hint: str | None = None,
    lang_hint: str | None = None,
) -> tuple[int, int] | None:
    """
    Find the 0-indexed start and end line bounds (exclusive) of a symbol
    in the given code string using tree-sitter.
    """
    lang = lang_hint
    if not lang and file_path_hint:
        lang = detect_language(file_path_hint)
    if not lang:
        src = code.encode("utf-8", errors="replace")
        if b"fn " in src and (b"impl " in src or b"pub " in src):
            lang = "rust"
        elif b"func " in src:
            lang = "go"
        elif b"def " in src or (b"import " in src and b":" in src):
            lang = "python"
        elif b"class " in src and (b"public " in src or b"private " in src or b"void " in src):
            lang = "java"
        elif b"const " in src or b"let " in src or b"function " in src or b"=>" in src:
            lang = "javascript"
        else:
            lang = "python"

    if lang not in PARSERS:
        lang = "python"

    source_bytes = code.encode("utf-8", errors="replace")
    parser = PARSERS[lang]
    local_parser = Parser(parser.language)
    tree = local_parser.parse(source_bytes)

    fn_types  = BLOCK_FUNCTION_TYPES.get(lang, set())
    cls_types = BLOCK_CLASS_TYPES.get(lang, set())

    target_node = None

    def walk(node):
        nonlocal target_node
        if target_node is not None:
            return

        if node.is_named is False:
            return

        node_name = _node_top_name(node, lang)
        if node_name == name:
            is_match = False
            if kind == "function" and (node.type in fn_types or (node.type == "decorated_definition" and lang == "python")):
                is_match = True
            elif kind == "class" and (node.type in cls_types or (node.type == "decorated_definition" and lang == "python")):
                is_match = True
            elif kind == "constant" and _is_constant_node(node, lang):
                is_match = True

            if is_match:
                target_node = node
                return

        for child in node.children:
            walk(child)

    walk(tree.root_node)

    if target_node:
        start = target_node.start_point[0]
        end   = target_node.end_point[0] + 1
        return start, end

    return None


def get_function(path: str, name: str) -> FunctionResult | None:
    """Parse the file. Find symbol with matching name and kind=='function' or 'method'."""
    symbols = parse_file(path)
    for sym in symbols:
        if sym.name == name and sym.kind in ("function", "method"):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                source = "".join(lines[sym.line_start - 1 : sym.line_end])
                return FunctionResult(
                    name=sym.name,
                    file=path,
                    line_start=sym.line_start,
                    line_end=sym.line_end,
                    source=source
                )
            except Exception:
                return None
    return None

def get_class(path: str, name: str) -> FunctionResult | None:
    """Same as get_function but for kind=='class'."""
    symbols = parse_file(path)
    for sym in symbols:
        if sym.name == name and sym.kind == "class":
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                source = "".join(lines[sym.line_start - 1 : sym.line_end])
                return FunctionResult(
                    name=sym.name,
                    file=path,
                    line_start=sym.line_start,
                    line_end=sym.line_end,
                    source=source
                )
            except Exception:
                return None
    return None

def get_imports(path: str) -> list[str]:
    """Walk AST for import statements based on language and return import lines."""
    lang = detect_language(path)
    if not lang or lang not in PARSERS:
        return []
        
    try:
        with open(path, "rb") as f:
            source_bytes = f.read()
    except Exception:
        return []
        
    parser = PARSERS[lang]
    local_parser = Parser(parser.language)
    tree = local_parser.parse(source_bytes)
    
    imports = []
    import_types = IMPORT_NODE_TYPES.get(lang, set())
    
    def walk(node):
        if node.type in import_types:
            import_str = node.text.decode(errors="replace")
            imports.append(import_str)
        else:
            for child in node.children:
                walk(child)
                
    walk(tree.root_node)
    return imports

def _get_call_target(node):
    if node.type in ("call", "call_expression"):
        return node.child_by_field_name("function")
    elif node.type == "method_call_expression":
        target = node.child_by_field_name("name")
        if not target:
            target = node.child_by_field_name("function")
        return target
    elif node.type == "method_invocation":
        return node.child_by_field_name("name")
    return None

def _extract_callee_name(target_node) -> str | None:
    if not target_node:
        return None
    # If it is a simple identifier, return its text
    if target_node.type == "identifier":
        return target_node.text.decode(errors="replace")
    
    # If it's a member/attribute/field access, we want the property name
    # e.g., obj.method() -> method
    for field_name in ("attribute", "property", "field", "name"):
        child = target_node.child_by_field_name(field_name)
        if child:
            return _extract_callee_name(child)
            
    # As a robust fallback, find the last identifier in the target_node subtree
    last_id = None
    def find_last_identifier(n):
        nonlocal last_id
        if n.type == "identifier":
            last_id = n
        for child in n.children:
            find_last_identifier(child)
    find_last_identifier(target_node)
    if last_id:
        return last_id.text.decode(errors="replace")
        
    return None

def extract_calls(path: str) -> list[tuple[int, str]]:
    """
    Parse file and extract all function/method call target names and their line numbers.
    Returns a list of (line, callee_name) tuples.
    """
    lang = detect_language(path)
    if not lang or lang not in PARSERS:
        return []
        
    try:
        with open(path, "rb") as f:
            source_bytes = f.read()
    except Exception:
        return []
        
    parser = PARSERS[lang]
    local_parser = Parser(parser.language)
    tree = local_parser.parse(source_bytes)
    
    calls = []
    
    def walk(node):
        target = _get_call_target(node)
        if target:
            callee_name = _extract_callee_name(target)
            if callee_name:
                line = node.start_point[0] + 1
                calls.append((line, callee_name))
        for child in node.children:
            walk(child)
            
    walk(tree.root_node)
    return calls


def extract_references(path: str, symbol_names: set[str]) -> list[tuple[str, int]]:
    """
    Parse file and find all identifier nodes matching any name in symbol_names.

    Returns a list of (symbol_name, line) tuples for every reference found.
    References include: plain identifiers, attribute access (obj.Name),
    import usage, assignments, and return values.
    """
    lang = detect_language(path)
    if not lang or lang not in PARSERS:
        return []

    try:
        with open(path, "rb") as f:
            source_bytes = f.read()
    except Exception:
        return []

    parser = PARSERS[lang]
    local_parser = Parser(parser.language)
    tree = local_parser.parse(source_bytes)

    refs: list[tuple[str, int]] = []

    # Node types that should be skipped to avoid counting definitions as references
    def _is_definition_node(node) -> bool:
        if lang == "python":
            if node.type == "function_definition" or node.type == "class_definition":
                return True
            if node.type == "decorated_definition":
                for child in node.children:
                    if child.type in ("function_definition", "class_definition"):
                        return True
        elif lang in ("javascript", "typescript"):
            if node.type in ("function_declaration", "class_declaration",
                             "generator_function_declaration"):
                return True
        elif lang == "java":
            if node.type in ("method_declaration", "class_declaration",
                             "constructor_declaration"):
                return True
        elif lang == "go":
            if node.type in ("function_declaration", "method_declaration",
                             "type_declaration"):
                return True
        elif lang == "rust":
            if node.type in ("function_item", "impl_item", "struct_item",
                             "trait_item", "enum_item"):
                return True
        return False

    def walk(node):
        # Skip the *signature* of definition nodes (the def/class line itself),
        # but still walk into the body to find references within.
        if _is_definition_node(node):
            # Only skip the name node of the definition, not the body
            for child in node.children:
                # Skip the name/identifier child of the definition node
                if child.type == "identifier":
                    continue
                walk(child)
            return

        # Check identifier / field / attribute nodes
        if node.type == "identifier" or node.type == "field_identifier":
            name = node.text.decode(errors="replace")
            if name in symbol_names:
                refs.append((name, node.start_point[0] + 1))

        # Python: attribute access like obj.Name or module.Name
        if node.type == "attribute":
            attr_node = node.child_by_field_name("attribute")
            if attr_node:
                name = attr_node.text.decode(errors="replace")
                if name in symbol_names:
                    refs.append((name, attr_node.start_point[0] + 1))

        # Java/Rust: scoped identifiers like self.Name, crate::module::Name
        if node.type == "scoped_identifier":
            # The last part of the scope is the actual symbol
            parts = node.text.decode(errors="replace").split("::")
            if parts:
                last = parts[-1]
                if last in symbol_names:
                    refs.append((last, node.start_point[0] + 1))

        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return refs


def extract_imports_structured(path: str) -> list[tuple[str, int, int]]:
    """
    Parse file and extract structured import data for database storage.

    Returns a list of (module, level, is_star) tuples:
        - module: The imported module path (e.g. "os", "models.user", ".utils")
        - level:  Relative import depth (0 = absolute, 1 = one dot, 2 = two dots, etc.)
        - is_star: 1 if "from x import *", else 0
    """
    lang = detect_language(path)
    if not lang or lang not in PARSERS:
        return []

    try:
        with open(path, "rb") as f:
            source_bytes = f.read()
    except Exception:
        return []

    parser = PARSERS[lang]
    local_parser = Parser(parser.language)
    tree = local_parser.parse(source_bytes)

    import_types = IMPORT_NODE_TYPES.get(lang, set())
    results: list[tuple[str, int, int]] = []

    def walk(node):
        if node.type in import_types:
            text = node.text.decode(errors="replace").strip()
            module = ""
            level = 0
            is_star = 0

            if lang == "python":
                if node.type == "import_from_statement":
                    # Count leading dots for relative import level
                    full_text = node.text.decode(errors="replace")
                    level = 0
                    for ch in full_text:
                        if ch == '.':
                            level += 1
                        else:
                            break
                    # Extract module name (after dots, before "import")
                    # e.g. "from .utils import auth" -> ".utils"
                    # e.g. "from models.user import User" -> "models.user"
                    module_part = text.split("import")[0].strip()
                    # Remove "from" keyword
                    if module_part.startswith("from"):
                        module_part = module_part[4:].strip()
                    # Remove trailing dots and spaces
                    module = module_part.strip()
                    # Check for star import
                    if "import *" in text:
                        is_star = 1
                elif node.type == "import_statement":
                    # "import os" or "import os as operating_system"
                    # or "import os.path" or "import models.user"
                    module_part = text.replace("import", "").strip()
                    # Handle "as" alias: "import os as operating_system" -> "os"
                    if " as " in module_part:
                        module_part = module_part.split(" as ")[0].strip()
                    module = module_part

            elif lang in ("javascript", "typescript"):
                # import ... from 'module'
                if "from" in text:
                    # Extract between from and the quote
                    after_from = text.split("from")[-1].strip()
                    module = after_from.strip("'\"; ")
                elif "require(" in text:
                    # const x = require('module')
                    import re
                    m = re.search(r"require\(['\"](.+?)['\"]\)", text)
                    if m:
                        module = m.group(1)

            elif lang == "java":
                # import com.example.MyClass;
                module = text.replace("import", "").replace(";", "").strip()
                if module.startswith("static "):
                    module = module[7:].strip()

            elif lang == "go":
                # import "fmt" or import ( "os" \n "path" )
                import re
                m = re.search(r'"(.+?)"', text)
                if m:
                    module = m.group(1)

            elif lang == "rust":
                # use crate::module::Name;
                module = text.replace("use", "").replace(";", "").strip()

            if module:
                results.append((module, level, is_star))

        else:
            for child in node.children:
                walk(child)

    walk(tree.root_node)
    return results


def extract_docstrings(path: str) -> list[tuple[str, str, int, int]]:
    """
    Parse file and extract docstrings for each function/class symbol.

    Returns a list of (symbol_name, docstring_content, line_start, line_end) tuples.
    Only includes symbols that actually have a docstring.
    """
    lang = detect_language(path)
    if not lang or lang not in PARSERS:
        return []

    try:
        with open(path, "rb") as f:
            source_bytes = f.read()
    except Exception:
        return []

    parser = PARSERS[lang]
    local_parser = Parser(parser.language)
    tree = local_parser.parse(source_bytes)

    node_types = NODE_TYPES.get(lang, {})
    results: list[tuple[str, str, int, int]] = []

    def _extract_docstring_from_node(node) -> str | None:
        """Extract the first string literal after a function/class definition."""
        # Walk children looking for a string expression right after the signature
        if lang == "python":
            # Python docstrings are the first expression_statement in the body
            for child in node.children:
                if child.type == "block":
                    for stmt in child.children:
                        if stmt.type == "expression_statement":
                            expr = stmt.children[0] if stmt.children else None
                            if expr and expr.type == "string":
                                return expr.text.decode(errors="replace")
                        # Skip any non-string statement (docstring must be first)
                        break
            # Try direct string child (some AST representations)
            for child in node.children:
                if child.type == "string":
                    return child.text.decode(errors="replace")
        elif lang in ("javascript", "typescript"):
            # JS/TS: look for comment blocks before the function, or first string in body
            for child in node.children:
                if child.type == "statement_block":
                    for stmt in child.children:
                        if stmt.type == "expression_statement":
                            expr = stmt.children[0] if stmt.children else None
                            if expr and expr.type == "string":
                                return expr.text.decode(errors="replace")
                        break
        elif lang == "java":
            # Java: look for first statement in method body that's a string
            for child in node.children:
                if child.type in ("block", "class_body"):
                    for stmt in child.children:
                        if stmt.type == "expression_statement":
                            expr = stmt.children[0] if stmt.children else None
                            if expr and expr.type == "string_literal":
                                return expr.text.decode(errors="replace")
                        break
        elif lang == "go":
            # Go: docstring is the comment group before the declaration
            # For now, check first statement in function body
            for child in node.children:
                if child.type == "block":
                    for stmt in child.children:
                        if stmt.type == "expression_statement":
                            expr = stmt.children[0] if stmt.children else None
                            if expr and expr.type == "raw_string_literal":
                                return expr.text.decode(errors="replace")
                        break
        elif lang == "rust":
            # Rust: docstrings are outer attributes (/// comments)
            # For now, check for string in first statement
            for child in node.children:
                if child.type == "block":
                    for stmt in child.children:
                        if stmt.type == "expression_statement":
                            expr = stmt.children[0] if stmt.children else None
                            if expr and expr.type == "string_literal":
                                return expr.text.decode(errors="replace")
                        break
        return None

    def walk(node):
        if node.type in node_types:
            name = _extract_name(node)
            if name:
                docstring = _extract_docstring_from_node(node)
                if docstring:
                    # Strip surrounding quotes
                    stripped = docstring.strip()
                    for quote in ('"""', "'''", '"""', "'''", '"', "'"):
                        if stripped.startswith(quote) and stripped.endswith(quote) and len(stripped) >= 2 * len(quote):
                            stripped = stripped[len(quote):-len(quote)].strip()
                            break
                    results.append((name, stripped, node.start_point[0] + 1, node.end_point[0] + 1))
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return results

