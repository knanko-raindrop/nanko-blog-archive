"""Independently compare generated HTML with the original export and check local links."""
from __future__ import annotations

import hashlib
import html
import json
import re
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class Document(HTMLParser):
    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.links = []
        self.h1 = []
        self.body = []
        self.category = []
        self.times = []
        self.article_links = []
        self.rel_links = {}
        self.body_links = []
        self.site_titles = []
        self.site_footers = []
        self.page_title = []
        self.archive_notices = []
        self.notices = []
        self.paragraphs = 0
        self.lists = 0
        self.stack = []
        self.forbidden = []
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            assert attrs["id"] not in self.ids, "Duplicate ID"
            self.ids.add(attrs["id"])
        if tag in {"img", "script", "iframe", "object", "embed"}:
            self.forbidden.append(tag)
        for key in ("href", "src"):
            if key in attrs:
                self.links.append(attrs[key])
        if tag == "a" and attrs.get("href", "").startswith("articles/"):
            self.article_links.append(attrs["href"])
        if tag == "a" and attrs.get("rel") in {"prev", "next"}:
            self.rel_links[attrs["rel"]] = attrs["href"]
        if any(a.get("class") == "article-body" for _, a in self.stack):
            if tag == "a":
                self.body_links.append(attrs["href"])
            if tag == "p":
                self.paragraphs += 1
            if tag == "ul":
                self.lists += 1
        if tag == "time":
            self.times.append(attrs.get("datetime"))
        if tag not in {"meta", "link", "br", "hr", "img", "input"}:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        assert self.stack and self.stack[-1][0] == tag, f"Unbalanced HTML: {tag}"
        self.stack.pop()

    def handle_data(self, data):
        if any(t == "title" for t, _ in self.stack):
            self.page_title.append(data)
        if any(a.get("class") == "site-title" for _, a in self.stack):
            self.site_titles.append(data)
        if any(t == "footer" for t, _ in self.stack):
            self.site_footers.append(data)
        if any(a.get("class") == "archive-notice" for _, a in self.stack):
            self.archive_notices.append(data)
        if any(a.get("class") == "historical-notice" for _, a in self.stack):
            self.notices.append(data)
        if any(t == "h1" for t, _ in self.stack):
            self.h1.append(data)
        if any(a.get("class") == "article-body" for _, a in self.stack):
            self.body.append(data)
        if any(a.get("class") == "category" for _, a in self.stack):
            self.category.append(data)


def validate() -> None:
    raw = (ROOT / "jugem0.txt").read_text(encoding="utf-8-sig")
    # Separate implementation from generate.py, so parsing mistakes cannot silently agree.
    source_records = [r.strip("\n") for r in raw.split("\n----\n") if r.strip()]
    assert len(source_records) == 74, f"Expected 74 source records, got {len(source_records)}"
    documents = {}
    for path in [ROOT / "index.html", *sorted((ROOT / "articles").glob("*.html"))]:
        text = path.read_text(encoding="utf-8")
        assert '<meta charset="utf-8">' in text and 'lang="ja"' in text, path
        assert 'name="viewport"' in text, path
        assert "\ufffd" not in text, f"Replacement character in {path}"
        document = Document(text)
        assert not document.stack, f"Unclosed HTML in {path}"
        assert not document.forbidden, f"Unexpected image or active content in {path}"
        assert "".join(document.site_titles) == "研究生活の雑記帳 2nd", path
        assert "".join(document.site_footers) == "研究生活の雑記帳 2nd · 2010–2021", path
        assert "".join(document.notices) == "記事は投稿当時の情報を保存したものです。現在の情報とは異なる可能性があります。", path
        documents[path.resolve()] = document
    assert len(documents) == 75, "Expected index plus 74 articles"
    expected = []
    counts = Counter()
    body_characters = 0
    for number, record in enumerate(source_records, 1):
        title, author, category, timestamp, blank, body = record.split("\n", 5)
        assert blank == ""
        date = datetime.strptime(timestamp, "%Y/%m/%d %H:%M:%S")
        filename = f"{date:%Y%m%d}-{number:03d}.html"
        document = documents[(ROOT / "articles" / filename).resolve()]
        assert "".join(document.h1) == html.unescape(title), f"Title mismatch: {filename}"
        assert "".join(document.page_title) == f"{html.unescape(title)} | 研究生活の雑記帳 2nd", f"Browser title mismatch: {filename}"
        assert document.times == [date.isoformat()], f"Date mismatch: {filename}"
        assert "".join(document.category) == html.unescape(category), f"Category mismatch: {filename}"
        expected_body = html.unescape(body.strip("\n"))
        assert "".join(document.body) == expected_body, f"Body mismatch: {filename}"
        assert document.body_links == re.findall(r"https?://[^\s<>]+", expected_body), f"Invented or missing body link: {filename}"
        assert document.paragraphs + document.lists > 0, f"Missing body structure: {filename}"
        body_characters += len(expected_body)
        expected.append((date, number, filename))
        counts[date.year] += 1
    expected.sort()
    index = documents[(ROOT / "index.html").resolve()]
    assert "".join(index.page_title) == "研究生活の雑記帳 2nd", "Index browser title mismatch"
    assert "".join(index.h1) == "南光一樹のブログアーカイブ（2010–2021）", "Archive heading mismatch"
    assert "".join(index.archive_notices) == "旧JUGEMブログ「研究生活の雑記帳 2nd」の記事を保存したアーカイブです。ブログの更新は終了しています。", "Archive notice mismatch"
    assert (ROOT / ".nojekyll").is_file(), "Missing GitHub Pages .nojekyll file"
    assert index.article_links == [f"articles/{name}" for _, _, name in reversed(expected)], "Index order or article coverage mismatch"
    for year in counts:
        assert f"year-{year}" in index.ids, "Missing year navigation target"
    for position, (_, _, name) in enumerate(expected):
        links = {}
        if position:
            links["prev"] = expected[position-1][2]
        if position + 1 < len(expected):
            links["next"] = expected[position+1][2]
        assert documents[(ROOT / "articles" / name).resolve()].rel_links == links, f"Incorrect previous/next links: {name}"
    external = set()
    local_count = 0
    for path, document in documents.items():
        for link in document.links:
            parsed = urlsplit(link)
            if parsed.scheme:
                assert parsed.scheme in {"https", "http"}, f"Unsafe URL: {link}"
                external.add(link)
                continue
            assert not parsed.netloc and not parsed.path.startswith("/"), f"Nonrelative URL: {link}"
            target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
            assert target.is_relative_to(ROOT), f"Link escapes project: {link}"
            assert target.is_file(), f"Broken local link in {path.name}: {link}"
            if parsed.fragment:
                assert target in documents and unquote(parsed.fragment) in documents[target].ids, f"Missing anchor: {link}"
            local_count += 1
    report = {
        "articles": len(expected), "first_date": expected[0][0].isoformat(),
        "last_date": expected[-1][0].isoformat(), "articles_per_year": dict(sorted(counts.items())),
        "body_characters_verified": body_characters, "local_links_checked": local_count,
        "body_paragraphs": sum(d.paragraphs for d in documents.values()),
        "body_lists": sum(d.lists for d in documents.values()),
        "external_urls": sorted(external),
        "external_status": "Not checked by this validator; preserved original URLs may be unavailable.",
        "source_sha256": hashlib.sha256((ROOT / "jugem0.txt").read_bytes()).hexdigest(),
        "result": "PASS",
    }
    directory = ROOT / ".local-reports"
    directory.mkdir(exist_ok=True)
    (directory / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    validate()
