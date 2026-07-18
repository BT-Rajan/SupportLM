from app.services.chunking import chunk_markdown


def test_chunks_by_heading():
    md = "# Setup\n\nInstall steps here.\n\n## Installation\n\nRun pip install.\n"
    chunks = chunk_markdown(md)
    assert len(chunks) == 2
    assert chunks[0].heading_path == "Setup"
    assert chunks[1].heading_path == "Setup > Installation"


def test_no_headings_returns_single_chunk():
    md = "Just plain text, no headings."
    chunks = chunk_markdown(md)
    assert len(chunks) == 1
    assert chunks[0].heading_path is None
