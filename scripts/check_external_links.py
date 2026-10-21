"""Optional network check. HTTP errors are candidates, not proof a URL is dead."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def check(url):
    result = {"url": url}
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ArchiveLinkCheck/1.0)"})
        with urlopen(request, timeout=10) as response:
            result.update(status=response.status, final_url=response.url, result="reachable")
    except HTTPError as error:
        result.update(status=error.code, result="needs_review", detail=str(error))
    except (URLError, TimeoutError, OSError) as error:
        result.update(result="unconfirmed", detail=str(error))
    return result


if __name__ == "__main__":
    directory = ROOT / ".local-reports"
    validation = json.loads((directory / "validation.json").read_text(encoding="utf-8"))
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(check, validation["external_urls"]))
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "results": results,
              "note": "403/429 may reflect bot restrictions. Network failures do not prove a link is dead. Source URLs are unchanged."}
    (directory / "external-links.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
