import os
import tempfile
import shutil
import git
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from codeengine.app import app
from codeengine.database.sqlite import init_db, DB_PATH
from codeengine.core.edit_engine import _pending

@pytest.fixture(autouse=True)
def setup_teardown_db():
    """Swap real DB with temporary DB path during tests."""
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
    """Create and configure a temp git repo with a test file."""
    temp_dir = tempfile.mkdtemp()
    temp_path = Path(temp_dir)
    repo = git.Repo.init(temp_dir)
    
    test_file = temp_path / "test_file.py"
    test_file.write_text(
        "def test_func():\n"
        "    print('hello api')\n",
        encoding="utf-8"
    )
    
    repo.index.add([str(test_file)])
    repo.index.commit("Initial commit")
    
    os.environ["REPO_PATH"] = temp_dir
    
    yield temp_dir
    
    shutil.rmtree(temp_dir, ignore_errors=True)
    if "REPO_PATH" in os.environ:
        del os.environ["REPO_PATH"]

def test_search_code_api(temp_repo):
    """Test GET /search/code returns correct code matches."""
    with TestClient(app) as cl:
        response = cl.get(f"/search/code?q=print&path={temp_repo}&lang=python")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert "hello api" in data["matches"][0]["text"]

def test_search_file_api(temp_repo):
    """Test GET /search/file returns matching files."""
    with TestClient(app) as cl:
        response = cl.get(f"/search/file?pattern=test_file&root={temp_repo}")
        assert response.status_code == 200
        files = response.json()
        assert len(files) == 1
        assert "test_file.py" in files[0]

def test_get_function_api(temp_repo):
    """Test GET /search/function returns the source code of the requested function."""
    with TestClient(app) as cl:
        test_file_path = os.path.join(temp_repo, 'test_file.py')
        response = cl.get(f"/search/function?file={test_file_path}&name=test_func")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test_func"
        assert "hello api" in data["source"]

# def test_edit_preview_and_apply_api(temp_repo):
#     """Test full cycle of POST /preview-edit, POST /apply-edit, and POST /undo endpoints."""
#     with TestClient(app) as cl:
#         req_data = {
#             "file": "test_file.py",
#             "old_code": "print('hello api')",
#             "new_code": "print('hello fastapi')"
#         }
#         
#         # Test preview-edit
#         resp = cl.post("/preview-edit", json=req_data)
#         assert resp.status_code == 200
#         preview = resp.json()
#         assert preview["lines_changed"] == 2
#         assert preview["edit_id"] in _pending
#         
#         # Test apply-edit
#         apply_resp = cl.post("/apply-edit", json={"edit_id": preview["edit_id"]})
#         assert apply_resp.status_code == 200
#         apply_data = apply_resp.json()
#         assert apply_data["commit_hash"] is not None
#         
#         # Test undo-edit
#         undo_resp = cl.post("/undo")
#         assert undo_resp.status_code == 200
#         undo_data = undo_resp.json()
#         assert undo_data["reverted_commit"] is not None

def test_request_logging_middleware(temp_repo):
    """Test that requests are logged to requests.log when logging is enabled."""
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_file = log_dir / "requests.log"
    
    # Ensure log file doesn't exist or is cleared before test
    if log_file.exists():
        log_file.unlink()
        
    original_logging = os.environ.get("LOGGING")
    try:
        os.environ["LOGGING"] = "true"
        with TestClient(app) as cl:
            response = cl.get(f"/search/file?pattern=test_file&root={temp_repo}")
            assert response.status_code == 200
            
            # Check that log file was created and contains a log entry
            assert log_file.exists()
            log_content = log_file.read_text(encoding="utf-8")
            assert "/search/file" in log_content
            assert "GET" in log_content
            assert "200" in log_content
            
        # Clean up the log file
        log_file.unlink()
        
        # Test that logging is NOT done when LOGGING is set to false
        os.environ["LOGGING"] = "false"
        with TestClient(app) as cl:
            response = cl.get(f"/search/file?pattern=test_file&root={temp_repo}")
            assert response.status_code == 200
            assert not log_file.exists()
            
    finally:
        if original_logging is not None:
            os.environ["LOGGING"] = original_logging
        elif "LOGGING" in os.environ:
            del os.environ["LOGGING"]

def test_call_graph_and_endpoints():
    """Test full call graph indexing and all call graph endpoints."""
    temp_dir = tempfile.mkdtemp()
    temp_path = Path(temp_dir)
    repo = git.Repo.init(temp_dir)
    
    # Create a source file with caller -> callee relationship
    test_file = temp_path / "payment.py"
    test_file.write_text(
        "def validate_card():\n"
        "    return True\n"
        "\n"
        "def charge_customer():\n"
        "    validate_card()\n"
        "    return 'success'\n",
        encoding="utf-8"
    )
    
    repo.index.add([str(test_file)])
    repo.index.commit("Initial commit")
    
    original_repo = os.environ.get("REPO_PATH")
    os.environ["REPO_PATH"] = temp_dir
    
    try:
        with TestClient(app) as cl:
            # Reindex the temp repository so index_repo runs on it
            # and populates files, symbols, and call_edges
            reindex_resp = cl.post("/reindex", json={"repo_path": temp_dir})
            assert reindex_resp.status_code == 200
            
            # 1. Test GET /search/index
            index_resp = cl.get("/search/index")
            assert index_resp.status_code == 200
            index_data = index_resp.json()
            assert len(index_data) == 1
            assert index_data[0]["file"] == "payment.py"
            symbols = {s["name"]: s for s in index_data[0]["symbols"]}
            assert "validate_card" in symbols
            assert "charge_customer" in symbols
            
            # 2. Test GET /search/overview
            overview_resp = cl.get("/search/overview")
            assert overview_resp.status_code == 200
            overview = overview_resp.json()
            assert len(overview["edges"]) == 1
            edge = overview["edges"][0]
            assert edge["caller_name"] == "charge_customer"
            assert edge["callee_name"] == "validate_card"
            assert edge["caller_file"] == "payment.py"
            
            # 3. Test GET /search/callers
            callers_resp = cl.get("/search/callers?symbol_name=validate_card")
            assert callers_resp.status_code == 200
            callers = callers_resp.json()
            assert len(callers) == 1
            assert callers[0]["caller_name"] == "charge_customer"
            
            # 4. Test GET /search/callees
            callees_resp = cl.get("/search/callees?symbol_name=charge_customer")
            assert callees_resp.status_code == 200
            callees = callees_resp.json()
            assert len(callees) == 1
            assert callees[0]["callee_name"] == "validate_card"
            
            # 5. Test GET /search/function-signature
            sig_resp = cl.get(
                f"/search/function-signature?file=payment.py"
                f"&line_start={symbols['charge_customer']['line_start']}"
                f"&line_end={symbols['charge_customer']['line_end']}"
            )
            assert sig_resp.status_code == 200
            sig_data = sig_resp.json()
            assert sig_data["signature"].strip().startswith("def charge_customer():")
            assert sig_data["body"] is None
            
            # 6. Test GET /search/function-body
            body_resp = cl.get(
                f"/search/function-body?file=payment.py"
                f"&line_start={symbols['charge_customer']['line_start']}"
                f"&line_end={symbols['charge_customer']['line_end']}"
            )
            assert body_resp.status_code == 200
            body_data = body_resp.json()
            assert "validate_card()" in body_data["body"]
            
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if original_repo is not None:
            os.environ["REPO_PATH"] = original_repo
        elif "REPO_PATH" in os.environ:
            del os.environ["REPO_PATH"]

