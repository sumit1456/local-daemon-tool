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

