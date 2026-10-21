"""Build the archive using only Python's standard library. Never modify the export."""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "jugem0.txt"
SITE_TITLE = "研究生活の雑記帳 2nd"
HISTORICAL_NOTICE = "記事は投稿当時の情報を保存したものです。現在の情報とは異なる可能性があります。"
URL = re.compile(r"https?://[^\s<>]+")


@dataclass(frozen=True)
class Article:
    number: int
    title: str
    author: str
    category: str
    date: datetime
    body: str
    source_line: int

    @property
    def filename(self) -> str:
        return f"{self.date:%Y%m%d}-{self.number:03d}.html"


def read_articles() -> list[Article]:
    # Strict decoding: invalid bytes must fail rather than silently disappear.
    source = SOURCE.read_text(encoding="utf-8-sig")
    if "\ufffd" in source:
        raise ValueError("Source contains Unicode replacement characters")
    articles = []
    start = 0
    for separator in list(re.finditer(r"^----[ \t]*$", source, re.M)) + [None]:
        end = separator.start() if separator else len(source)
        raw = source[start:end]
        if raw.strip():
            content = raw.strip("\n")
            lines = content.split("\n")
            if len(lines) < 6 or lines[4].strip():
                raise ValueError(f"Unexpected record structure at article {len(articles) + 1}")
            title, author, category, timestamp = lines[:4]
            date = datetime.strptime(timestamp, "%Y/%m/%d %H:%M:%S")
            body = html.unescape("\n".join(lines[5:]).strip("\n"))
            if not title or not category or not body:
                raise ValueError("Missing required article field")
            # No HTML exists in this export; fail safely if a future export differs.
            if re.search(r"</?[A-Za-z][^>]*>", body):
                raise ValueError("HTML source requires explicit migration review")
            line = source.count("\n", 0, start + len(raw) - len(raw.lstrip("\n"))) + 1
            articles.append(Article(len(articles) + 1, html.unescape(title), author,
                                    html.unescape(category), date, body, line))
        start = separator.end() if separator else len(source)
    if len(articles) != 74:
        raise ValueError(f"Expected 74 articles; found {len(articles)}")
    return articles


def inline_html(body: str) -> str:
    # Keep every character and line break; only explicit URLs become links.
    parts, cursor = [], 0
    for match in URL.finditer(body):
        parts.append(html.escape(body[cursor:match.start()]))
        value = html.escape(match.group(), quote=True)
        parts.append(f'<a href="{value}" rel="noreferrer">{value}</a>')
        cursor = match.end()
    parts.append(html.escape(body[cursor:]))
    return "".join(parts)


def body_html(body: str) -> str:
    # Only blank lines and explicit, consecutive bullet lines establish structure.
    # Preserve delimiters and original markers so extracted text stays identical.
    result = []
    bullet = re.compile(r"^[ \t\u3000]*(?:[・●]|- +)\S")
    for block in re.split(r"(\n(?:[ \t\u3000]*\n)+)", body):
        if not block:
            continue
        if not block.strip():
            result.append(block)
            continue
        lines = block.splitlines(keepends=True)
        position = 0
        while position < len(lines):
            is_bullet = bool(bullet.match(lines[position]))
            end = position + 1
            while end < len(lines) and bool(bullet.match(lines[end])) == is_bullet:
                end += 1
            group = lines[position:end]
            if is_bullet and len(group) >= 2:
                items = []
                for line in group:
                    text = line.removesuffix("\n")
                    newline = "\n" if line.endswith("\n") else ""
                    items.append(f"<li>{inline_html(text)}</li>{newline}")
                result.append('<ul class="source-list">' + "".join(items) + "</ul>")
            else:
                result.append("<p>" + inline_html("".join(group)) + "</p>")
            position = end
    return "".join(result)


def page(title: str, content: str, prefix: str = "") -> str:
    return f'''<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="{prefix}styles.css">
</head>
<body>
  <a class="skip-link" href="#main">本文へ</a>
  <header class="site-header"><div class="container"><a class="site-title" href="{prefix}index.html">{SITE_TITLE}</a><span class="site-period">2010–2021</span></div></header>
  <main id="main" class="container">{content}</main>
  <footer class="site-footer container">{SITE_TITLE} · 2010–2021</footer>
</body>
</html>
'''


def metadata(article: Article) -> str:
    return (f'<div class="metadata"><time datetime="{article.date.isoformat()}">'
            f'{article.date:%Y年%m月%d日 %H:%M:%S}</time>'
            f'<span class="category">{html.escape(article.category)}</span></div>')


def review_report(articles: list[Article]) -> None:
    rules = {
        "生活・家族・健康": r"引っ越|自宅|家族|妻|子供|風邪|安否|被災|住居",
        "所属・職場・会議・人事": r"所属|職場|採用|転職|ポスドク|会議|議事|異動|転勤|退職",
        "研究上のやり取り・未公表情報": r"査読|共同研究|招待|投稿|未公開|未公表|謝金|業者",
        "連絡先・識別情報": r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b0\d{1,4}[-－]\d{1,4}[-－]\d{4}\b|住所|電話番号",
    }
    lines = ["# 公開前の確認候補（ローカル専用）", "",
             "原文を変更・削除せず、キーワードに基づいて抽出した確認候補です。",
             "危険性を断定するものではなく、人名や文脈を網羅的に判定するものでもありません。",
             "共著者名・第三者の記述、当時の所属や生活情報を含め、公開前に全記事を確認してください。",
             "このレポートは .gitignore で除外しています。", ""]
    for a in articles:
        hits = []
        for label, pattern in rules.items():
            matches = list(re.finditer(pattern, a.body))
            if matches:
                excerpts = [a.body[max(0, m.start()-30):m.end()+60].replace("\n", " ") for m in matches[:3]]
                hits.append(f"- {label}: " + " / ".join(excerpts))
        if hits:
            lines += [f"## {a.date:%Y-%m-%d} {a.title}", "",
                      f"記事: articles/{a.filename} / 元データ: jugem0.txt:{a.source_line}", "", *hits, ""]
    lines += ["## 元データの制約", "", "リンク文字列のみで参照URLが残っていない箇所があります。URLは補完していません。",
              "本文に明記された外部URLのみリンクにしました。外部サイトの継続稼働は保証できません。", ""]
    directory = ROOT / ".local-reports"
    directory.mkdir(exist_ok=True)
    (directory / "publication-review.md").write_text("\n".join(lines), encoding="utf-8")


def generate() -> None:
    articles = sorted(read_articles(), key=lambda a: (a.date, a.number))
    directory = ROOT / "articles"
    directory.mkdir(exist_ok=True)
    expected = {a.filename for a in articles}
    unexpected = {p.name for p in directory.glob("*.html")} - expected
    if unexpected:
        raise ValueError(f"Unexpected HTML files; review manually: {sorted(unexpected)}")
    for index, a in enumerate(articles):
        previous = articles[index-1] if index else None
        following = articles[index+1] if index+1 < len(articles) else None
        nav = []
        if previous:
            nav.append(f'<a href="{previous.filename}" rel="prev"><span>← 前の記事（古い）</span>{html.escape(previous.title)}</a>')
        if following:
            nav.append(f'<a href="{following.filename}" rel="next"><span>次の記事（新しい） →</span>{html.escape(following.title)}</a>')
        content = f'''
    <a class="back-link" href="../index.html#year-{a.date.year}">← 記事一覧へ戻る</a>
    <article>
      <header class="article-header"><h1>{html.escape(a.title)}</h1>{metadata(a)}</header>
      <p class="historical-notice">{HISTORICAL_NOTICE}</p>
      <div class="article-body">{body_html(a.body)}</div>
    </article>
    <nav class="article-nav" aria-label="前後の記事">{''.join(nav)}</nav>
    <a class="back-link" href="../index.html">記事一覧へ戻る</a>
'''
        (directory / a.filename).write_text(page(f"{a.title} | {SITE_TITLE}", content, "../"), encoding="utf-8")
    years = sorted({a.date.year for a in articles}, reverse=True)
    year_nav = "".join(f'<a href="#year-{y}">{y}</a>' for y in years)
    sections = []
    for year in years:
        group = [a for a in reversed(articles) if a.date.year == year]
        items = "".join(f'<li><time datetime="{a.date:%Y-%m-%d}">{a.date:%m.%d}</time><div><a href="articles/{a.filename}">{html.escape(a.title)}</a><span class="list-category">{html.escape(a.category)}</span></div></li>' for a in group)
        sections.append(f'<section class="year-section" id="year-{year}" aria-labelledby="heading-{year}"><h2 id="heading-{year}">{year}<small>{len(group)}記事</small></h2><ol class="article-list">{items}</ol></section>')
    content = f'''
    <div class="intro"><p class="eyebrow">BLOG ARCHIVE / 74 ARTICLES</p><h1>南光一樹のブログアーカイブ（2010–2021）</h1>
    <p class="archive-notice">旧JUGEMブログ「{SITE_TITLE}」の記事を保存したアーカイブです。ブログの更新は終了しています。</p>
    <p class="historical-notice">{HISTORICAL_NOTICE}</p>
    <p class="intro-period">2010年9月17日 — 2021年2月2日 · 全74記事</p></div>
    <nav class="year-nav" aria-label="年別の記事一覧">{year_nav}</nav>
    <div class="archive-list">{''.join(sections)}</div>
'''
    (ROOT / "index.html").write_text(page(SITE_TITLE, content), encoding="utf-8")
    review_report(articles)
    print(f"Generated {len(articles)} articles. Source SHA-256: {hashlib.sha256(SOURCE.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    generate()
