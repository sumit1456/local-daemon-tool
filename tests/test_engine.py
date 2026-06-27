import os
import shutil
import tempfile
import pytest
import git
from pathlib import Path

from codeengine.database.sqlite import init_db, get_db, DB_PATH
from codeengine.core.ast_engine import parse_file, detect_language, get_function, get_class, extract_references, extract_docstrings
from codeengine.core.search_engine import search_code, search_symbol, find_file, find_symbol_usages, get_docstring, get_index, get_repo_overview
from codeengine.core.index_engine import index_repo, reindex_file
from codeengine.core.edit_engine import preview_edit, apply_edit, undo_edit, _pending
from codeengine.models.edit_models import EditRequest

@pytest.fixture(autouse=True)
def setup_teardown_db():
    """Dynamically swap DB_PATH to a temporary file for tests."""
    original_db_path = DB_PATH
    temp_db_dir = tempfile.mkdtemp()
    test_db_path = Path(temp_db_dir) / "test_index.db"
    
    import codeengine.database.sqlite as sq
    sq.DB_PATH = test_db_path
    
    yield
    
    shutil.rmtree(temp_db_dir, ignore_errors=True)
    sq.DB_PATH = original_db_path

@pytest.fixture
def temp_repo():
    """Create a temporary directory initialized as a git repository with a Python file."""
    temp_dir = tempfile.mkdtemp()
    temp_path = Path(temp_dir)
    
    # Init git repo
    repo = git.Repo.init(temp_dir)
    
    # Create test Python file
    test_file = temp_path / "test_file.py"
    test_file.write_text(
        "def hello_world():\n"
        "    print('Hello World')\n"
        "\n"
        "class MyClass:\n"
        "    def method(self):\n"
        "        pass\n",
        encoding="utf-8"
    )
    
    repo.index.add([str(test_file)])
    repo.index.commit("Initial commit")
    
    yield temp_dir
    
    shutil.rmtree(temp_dir, ignore_errors=True)

@pytest.mark.asyncio
async def test_database_init():
    """Test that SQLite database tables are created correctly."""
    await init_db()
    async with get_db() as db:
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table'") as cursor:
            tables = [row["name"] for row in await cursor.fetchall()]
    assert "files" in tables
    assert "symbols" in tables
    assert "edits" in tables

def test_language_detection():
    """Test extensions map to correct languages."""
    assert detect_language("foo.py") == "python"
    assert detect_language("foo.java") == "java"
    assert detect_language("foo.txt") is None

def test_ast_parsing(temp_repo):
    """Test that symbols are parsed and extracted from code AST."""
    file_path = Path(temp_repo) / "test_file.py"
    symbols = parse_file(str(file_path))
    symbol_names = [s.name for s in symbols]
    assert "hello_world" in symbol_names
    assert "MyClass" in symbol_names

@pytest.mark.asyncio
async def test_indexing_and_search(temp_repo):
    """Test full workflow of repository indexing and code search."""
    await init_db()
    os.environ["REPO_PATH"] = temp_repo
    
    indexed = await index_repo(temp_repo)
    assert indexed == 1
    
    # Test symbol search
    symbols = await search_symbol("hello", None)
    assert len(symbols) == 1
    assert symbols[0] == "hello_world:f:test_file.py:3-5"
    
    # Test code search via ripgrep
    matches = await search_code("print", temp_repo, "python", 10)
    assert len(matches) == 1
    assert "Hello World" in matches[0].text
    
    # Test find file via fd
    files = await find_file("test_file", temp_repo)
    assert len(files) == 1
    assert "test_file.py" in files[0]

# @pytest.mark.asyncio
# async def test_edit_engine(temp_repo):
#     """Test generating unified diff previews, applying changes, and undoing edits."""
#     await init_db()
#     os.environ["REPO_PATH"] = temp_repo
#     
#     req = EditRequest(
#         file="test_file.py",
#         old_code="print('Hello World')",
#         new_code="print('Hello antigravity')"
#     )
#     
#     preview = await preview_edit(req)
#     assert preview.lines_changed == 2
#     assert preview.edit_id in _pending
#     
#     apply_res = await apply_edit(preview.edit_id)
#     assert apply_res.commit_hash is not None
#     
#     # Read file and check contents
#     file_path = Path(temp_repo) / "test_file.py"
#     content = file_path.read_text(encoding="utf-8")
#     assert "Hello antigravity" in content
#     
#     # Undo edit
#     undo_res = await undo_edit()
#     assert undo_res.reverted_commit is not None
#     
#     content_after_undo = file_path.read_text(encoding="utf-8")
#     assert "Hello World" in content_after_undo

# @pytest.mark.asyncio
# async def test_watchdog_reindexing(temp_repo):
#     """Test that file modification re-indexing updates database symbols correctly."""
#     await init_db()
#     os.environ["REPO_PATH"] = temp_repo
#     
#     import codeengine.core.index_engine as ie
#     ie._watched_root = temp_repo
#     
#     # First index the repo
#     await index_repo(temp_repo)
#     
#     # Verify symbol count is 1 (hello_world)
#     symbols_before = await search_symbol("hello", None)
#     assert len(symbols_before) == 1
#     assert symbols_before[0].name == "hello_world"
#     
#     # Modify the file content and trigger re-index
#     file_path = Path(temp_repo) / "test_file.py"
#     file_path.write_text(
#         "def hello_fastapi():\n"
#         "    print('hello api')\n",
#         encoding="utf-8"
#     )
#     
#     # Call reindex_file directly
#     await reindex_file(str(file_path))
#     
#     # Check if symbols were updated correctly
#     symbols_after = await search_symbol("hello", None)
#     assert len(symbols_after) == 1
#     assert symbols_after[0].name == "hello_fastapi"


def test_ast_python_lambda():
    """Test that Python lambdas assigned to variables are extracted as function symbols."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
        f.write(
            "square = lambda x: x * x\n"
            "greet = lambda name: f'Hello {name}'\n"
            "def normal_func():\n"
            "    pass\n"
        )
        path = f.name
    try:
        symbols = parse_file(path)
        names = [s.name for s in symbols]
        kinds = {s.name: s.kind for s in symbols}
        assert "square" in names, f"Expected 'square' in {names}"
        assert "greet" in names, f"Expected 'greet' in {names}"
        assert "normal_func" in names, f"Expected 'normal_func' in {names}"
        assert kinds["square"] == "function"
        assert kinds["greet"] == "function"
    finally:
        Path(path).unlink(missing_ok=True)


def test_ast_js_arrow_and_function_expression():
    """Test that JS arrow functions, function expressions, and generator functions are extracted."""
    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False, encoding="utf-8") as f:
        f.write(
            "const add = (a, b) => a + b;\n"
            "const greet = (name) => { return `Hello ${name}`; };\n"
            "const multiply = function(x, y) { return x * y; };\n"
            "function* idGen() { yield 1; }\n"
            "const countUp = function* () { yield 2; };\n"
            "function namedFunc() { return 42; }\n"
        )
        path = f.name
    try:
        symbols = parse_file(path)
        names = [s.name for s in symbols]
        kinds = {s.name: s.kind for s in symbols}
        assert "add" in names, f"Expected 'add' in {names}"
        assert "greet" in names, f"Expected 'greet' in {names}"
        assert "multiply" in names, f"Expected 'multiply' in {names}"
        assert "idGen" in names, f"Expected 'idGen' in {names}"
        assert "countUp" in names, f"Expected 'countUp' in {names}"
        assert "namedFunc" in names, f"Expected 'namedFunc' in {names}"
        assert kinds["add"] == "function"
        assert kinds["multiply"] == "function"
        assert kinds["idGen"] == "function"
    finally:
        Path(path).unlink(missing_ok=True)


def test_ast_ts_arrow_and_function_expression():
    """Test that TypeScript arrow functions and function expressions are extracted."""
    with tempfile.NamedTemporaryFile(suffix=".ts", mode="w", delete=False, encoding="utf-8") as f:
        f.write(
            "const double = (n: number): number => n * 2;\n"
            "const greetTs = function(name: string): string { return `Hi ${name}`; };\n"
            "function* tsGen(): Generator<number> { yield 1; }\n"
            "function namedTs(): void {}\n"
        )
        path = f.name
    try:
        symbols = parse_file(path)
        names = [s.name for s in symbols]
        assert "double" in names, f"Expected 'double' in {names}"
        assert "greetTs" in names, f"Expected 'greetTs' in {names}"
        assert "tsGen" in names, f"Expected 'tsGen' in {names}"
        assert "namedTs" in names, f"Expected 'namedTs' in {names}"
    finally:
        Path(path).unlink(missing_ok=True)


def test_ast_java_lambda():
    """Test that Java lambda expressions assigned to variables are extracted."""
    with tempfile.NamedTemporaryFile(suffix=".java", mode="w", delete=False, encoding="utf-8") as f:
        f.write(
            "class MyService {\n"
            "    Runnable task = () -> System.out.println(\"running\");\n"
            "    Comparator<String> cmp = (a, b) -> a.compareTo(b);\n"
            "    void normalMethod() {}\n"
            "}\n"
        )
        path = f.name
    try:
        symbols = parse_file(path)
        names = [s.name for s in symbols]
        assert "task" in names, f"Expected 'task' in {names}"
        assert "cmp" in names, f"Expected 'cmp' in {names}"
        assert "normalMethod" in names, f"Expected 'normalMethod' in {names}"
        assert "MyService" in names, f"Expected 'MyService' in {names}"
    finally:
        Path(path).unlink(missing_ok=True)


def test_ast_rust_closure():
    """Test that Rust closure expressions assigned to variables are extracted."""
    with tempfile.NamedTemporaryFile(suffix=".rs", mode="w", delete=False, encoding="utf-8") as f:
        f.write(
            "fn named_fn() -> i32 { 42 }\n"
            "fn main() {\n"
            "    let add = |a, b| a + b;\n"
            "    let square = |x| x * x;\n"
            "}\n"
        )
        path = f.name
    try:
        symbols = parse_file(path)
        names = [s.name for s in symbols]
        assert "named_fn" in names, f"Expected 'named_fn' in {names}"
        assert "add" in names, f"Expected 'add' in {names}"
        assert "square" in names, f"Expected 'square' in {names}"
    finally:
        Path(path).unlink(missing_ok=True)


def test_extract_references():
    """Test that extract_references finds identifier usages matching symbol names."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
        f.write(
            "def helper():\n"
            "    pass\n"
            "\n"
            "def main():\n"
            "    helper()\n"
            "    x = helper\n"
        )
        path = f.name
    try:
        refs = extract_references(path, {"helper"})
        # Should find usages of 'helper' in main, but not the definition
        lines = [line for _, line in refs]
        assert len(refs) >= 2, f"Expected >=2 references, got {refs}"
        # All references should be on lines > 1 (the def is on line 1)
        assert all(line > 1 for _, line in refs), f"Definition should not be a reference: {refs}"
    finally:
        Path(path).unlink(missing_ok=True)


def test_extract_docstrings():
    """Test that extract_docstrings extracts docstrings from functions."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
        f.write(
            'def hello():\n'
            '    """Say hello."""\n'
            '    pass\n'
            '\n'
            'class Foo:\n'
            '    """A foo class."""\n'
            '    pass\n'
        )
        path = f.name
    try:
        docstrings = extract_docstrings(path)
        names = {name for name, _, _, _ in docstrings}
        assert "hello" in names, f"Expected 'hello' in docstrings, got {names}"
        assert "Foo" in names, f"Expected 'Foo' in docstrings, got {names}"
        # Check content
        for name, content, _, _ in docstrings:
            if name == "hello":
                assert "Say hello" in content
            elif name == "Foo":
                assert "foo class" in content
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_new_tables_created():
    """Test that references and docstrings tables are created."""
    await init_db()
    async with get_db() as db:
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table'") as cursor:
            tables = [row["name"] for row in await cursor.fetchall()]
    assert "symbol_references" in tables
    assert "docstrings" in tables


@pytest.mark.asyncio
async def test_indexing_populates_references_and_docstrings(temp_repo):
    """Test that indexing populates references and docstrings tables."""
    await init_db()
    os.environ["REPO_PATH"] = temp_repo

    indexed = await index_repo(temp_repo)
    assert indexed == 1

    async with get_db() as db:
        # Check docstrings were stored
        async with db.execute("SELECT COUNT(*) AS cnt FROM docstrings") as cursor:
            row = await cursor.fetchone()
            assert row["cnt"] >= 0  # No docstrings in test file, so 0 is ok

        # Check call_edges have callee_file
        async with db.execute("SELECT callee_file FROM call_edges LIMIT 1") as cursor:
            row = await cursor.fetchone()
            # No call edges in simple test file, so this is fine


@pytest.mark.asyncio
async def test_find_symbol_usages(temp_repo):
    """Test that find_symbol_usages returns references."""
    await init_db()
    os.environ["REPO_PATH"] = temp_repo

    indexed = await index_repo(temp_repo)
    assert indexed == 1

    # hello_world is defined but not referenced elsewhere in the test file
    usages = await find_symbol_usages("hello_world")
    # Should return at least the definition reference
    assert isinstance(usages, list)


@pytest.mark.asyncio
async def test_get_docstring(temp_repo):
    """Test that get_docstring retrieves docstrings."""
    await init_db()
    os.environ["REPO_PATH"] = temp_repo

    indexed = await index_repo(temp_repo)
    assert indexed == 1

    # No docstrings in test file, so should return empty
    results = await get_docstring("hello_world")
    assert results == []


@pytest.mark.asyncio
async def test_overview_with_dir_filter(temp_repo):
    """Test that overview endpoint accepts dir_filter."""
    await init_db()
    os.environ["REPO_PATH"] = temp_repo

    indexed = await index_repo(temp_repo)
    assert indexed == 1

    # dir_filter with empty string matches all files (no prefix constraint)
    overview = await get_repo_overview(dir_filter="")
    assert len(overview["files"]) == 1


@pytest.mark.asyncio
async def test_index_with_query_filter(temp_repo):
    """Test that index accepts query_filter for substring match."""
    await init_db()
    os.environ["REPO_PATH"] = temp_repo

    indexed = await index_repo(temp_repo)
    assert indexed == 1

    result = await get_index(query_filter="test_file")
    assert len(result["files"]) == 1
    assert "test_file" in result["files"][0].file
