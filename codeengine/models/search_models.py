from pydantic import BaseModel

class SearchRequest(BaseModel):
    """Schema for a code search request."""
    query: str
    path: str = "."
    lang: str | None = None      # filter by language: "python", "java", etc.
    limit: int = 50

class Match(BaseModel):
    """Schema representing a single line match in a file."""
    file: str
    line: int
    col: int
    text: str                    # the matching line content

class SearchResponse(BaseModel):
    """Schema representing search results."""
    matches: list[Match]
    total: int
    query: str

class Symbol(BaseModel):
    """Schema representing a syntax symbol extracted from the AST."""
    name: str
    kind: str                    # "function" | "class" | "method" | "interface"
    file: str
    line_start: int
    line_end: int

class FunctionResult(BaseModel):
    """Schema representing a single function search result with source code."""
    name: str
    file: str
    line_start: int
    line_end: int
    source: str                  # full source text of the function
