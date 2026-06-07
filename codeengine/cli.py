import uvicorn

def main():
    """Start the FastAPI server on port 8000."""
    print("Starting Universal Code Search & Edit Engine on http://localhost:8000...")
    uvicorn.run("codeengine.app:app", host="127.0.0.1", port=8000, reload=True)

if __name__ == "__main__":
    main()
