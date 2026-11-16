"""Exercise the competition project's normal Flask entry points."""

import io
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

import pymupdf


class PreviewFields(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "input" and "name" in fields and "value" in fields:
            if fields.get("type") != "checkbox" or "checked" in fields:
                self.values[fields["name"]] = fields["value"]


title = "Vector Retrieval Experiments"
source = Path(__file__).resolve().parent
sys.path.insert(0, str(source))
os.environ["OPENAI_API_KEY"] = ""


def main():
    with tempfile.TemporaryDirectory(prefix="qoder-smoke-") as data_dir:
        os.environ["DATA_DIR"] = data_dir
        from app import app

        app.testing = True
        with app.test_client() as client:
            for path in ("/", "/library", "/graph", "/search?q=vector", "/writing"):
                response = client.get(path)
                assert response.status_code == 200, (path, response.status_code)

            with pymupdf.open() as document:
                document.new_page().insert_text(
                    (72, 72), f"{title}\nAbstract\nA controlled study of vector retrieval for literature."
                )
                content = document.tobytes()
            preview = client.post("/upload/batch", data={"pdfs": (io.BytesIO(content), "sample.pdf")})
            assert preview.status_code == 200
            fields = PreviewFields()
            fields.feed(preview.get_data(as_text=True))
            fields.values.update(
                title_0=title, abstract_0="A controlled study of vector retrieval.",
                references_json_0='["A prior retrieval study"]',
            )
            saved = client.post("/upload/save_batch", data=fields.values, follow_redirects=True)
            assert saved.status_code == 200 and title in saved.get_data(as_text=True)
            search = client.get("/search?q=vector+retrieval")
            assert search.status_code == 200 and title in search.get_data(as_text=True)
            graph = client.get("/graph")
            assert graph.status_code == 200 and title in graph.get_data(as_text=True)
            outline = client.post("/writing/generate", data={"cluster": ""})
            assert outline.status_code == 200 and title in outline.get_data(as_text=True)

        def library_status(_):
            with app.test_client() as client:
                return client.get("/library").status_code

        with ThreadPoolExecutor(max_workers=4) as pool:
            assert list(pool.map(library_status, range(12))) == [200] * 12

        subprocess.run(
            [sys.executable, "-c", "from app import app; "
             "r = app.test_client().get('/library'); "
             f"assert r.status_code == 200 and {title!r} in r.get_data(as_text=True)"],
            cwd=source, check=True,
        )
    print("Upload, save, search, graph, outline, concurrent reads and restart passed.")


if __name__ == "__main__":
    main()
