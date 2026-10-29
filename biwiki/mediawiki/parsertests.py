# Reads and runs MediaWiki's parser test files (the format of MediaWiki 1.39 tests/parser/parserTests.txt and of
# wikimedia/parsoid's ParserTests\TestFileReader, (C) MediaWiki contributors, https://www.mediawiki.org/).
# Written by a3ref contributors on 2026-10-30 after that format and ParserTestRunner::runLegacyTest().
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""MediaWiki's own parser tests, run against the port.

    python -m biwiki.mediawiki.parsertests             # summary
    python -m biwiki.mediawiki.parsertests --show 5    # and the first failures, expected vs actual
    python -m biwiki.mediawiki.parsertests --filter quote --show 20
    python -m biwiki.mediawiki.parsertests --accept    # store the passing tests in tests/mediawiki/passing.txt
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent
TEST_FILE = ROOT / "tests" / "mediawiki" / "parserTests.txt"
PASSING_FILE = ROOT / "tests" / "mediawiki" / "passing.txt"

# Modes other than parsing a page (ParserTestRunner::runLegacyTest); not what the port is for
OTHER_MODES = {"pst", "msg", "section", "replace", "comment", "preload"}
DEFAULT_TITLE = "Parser test"


@dataclass
class ParserTest:
    name: str
    line: int
    sections: dict[str, str] = field(default_factory=dict)
    options: dict[str, object] = field(default_factory=dict)

    @property
    def wikitext(self) -> Optional[str]:
        return self.sections.get("wikitext")

    @property
    def legacy_html(self) -> Optional[str]:
        """What the legacy (PHP) parser is expected to produce: html/php, else the html shared with Parsoid."""
        return self.sections.get("html/php", self.sections.get("html"))

    def skip_reason(self) -> Optional[str]:
        if "disabled" in self.options or "html/php+disabled" in self.sections:
            return "disabled"
        if self.wikitext is None or self.legacy_html is None:
            return "no legacy parser test"
        modes = OTHER_MODES & set(self.options)
        if modes:
            return "mode " + ", ".join(sorted(modes))
        return None


@dataclass
class TestFile:
    articles: dict[str, str]
    tests: list[ParserTest]


_HEADER = re.compile(r"^!!\s*(\S*)\s*$")


def read(path: Path = TEST_FILE) -> TestFile:
    """The articles (pages the tests may use: templates and pages that exist) and the tests of a file."""
    articles: dict[str, str] = {}
    tests: list[ParserTest] = []
    lines = path.read_text(encoding="utf-8").split("\n")
    i = 0

    def section_body(start: int) -> tuple[list[str], int]:
        body = []
        j = start
        while j < len(lines) and not _HEADER.match(lines[j]):
            body.append(lines[j])
            j += 1
        return body, j

    while i < len(lines):
        m = _HEADER.match(lines[i])
        if not m:
            i += 1  # comments and blank lines between blocks
            continue
        kind = m.group(1).lower()
        if kind == "article":
            title_lines, i = section_body(i + 1)
            text_lines: list[str] = []
            if i < len(lines) and _HEADER.match(lines[i]).group(1).lower() == "text":
                text_lines, i = section_body(i + 1)
            articles[_normalize_title(" ".join(l.strip() for l in title_lines if l.strip()))] = "\n".join(text_lines)
            i += 1  # !! endarticle
        elif kind == "test":
            start = i + 1
            name_lines, i = section_body(i + 1)
            test = ParserTest(name=" ".join(l.strip() for l in name_lines if l.strip()), line=start)
            while i < len(lines):
                section = _HEADER.match(lines[i]).group(1).lower()
                if section == "end":
                    i += 1
                    break
                body, i = section_body(i + 1)
                test.sections[section] = "\n".join(body)
            test.options = parse_options(test.sections.get("options", ""))
            tests.append(test)
        else:
            # file-level blocks (!! version, !! options ... !! end, !! hooks ... !! endhooks): skipped
            _, i = section_body(i + 1)
            if i < len(lines) and _HEADER.match(lines[i]).group(1).lower() in ("end", "endhooks", "endfunctionhooks"):
                i += 1
    return TestFile(articles, tests)


_OPTION = re.compile(
    r"""(?P<name>[\w-]+)
        (?:\s*=\s*(?P<value>
            (?:"[^"]*"|\[\[[^\]]*\]\]|\{(?:[^{}]|\{[^{}]*\})*\}|[^"\s{}\[\],]+)
            (?:\s*,\s*(?:"[^"]*"|\[\[[^\]]*\]\]|[^"\s{}\[\],]+))*
        ))?""",
    re.X,
)


def parse_options(text: str) -> dict[str, object]:
    """``cat title=[[Foo]] language=de wgSomething="a b"`` -> {name: value or True}; a comma list -> a list."""
    out: dict[str, object] = {}
    for m in _OPTION.finditer(text):
        name, value = m.group("name").lower(), m.group("value")
        if value is None:
            out[name] = True
            continue
        parts = [_unquote(p.strip()) for p in re.split(r",(?![^\[]*\]\])", value)] if not value.startswith("{") else [value]
        out[name] = parts[0] if len(parts) == 1 else parts
    return out


def _unquote(v: str) -> str:
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    if v.startswith("[[") and v.endswith("]]"):
        return v[2:-2]
    return v


def _normalize_title(title: str) -> str:
    title = title.replace("_", " ").strip()
    return title[:1].upper() + title[1:]


# ---- running -------------------------------------------------------------------------------------------------

@dataclass
class Result:
    test: ParserTest
    passed: bool
    actual: str = ""
    error: str = ""


# Test options and !! config settings -> Config fields (ParserTestRunner::perTestSetup())
_SETTINGS = {
    "wgrawhtml": "raw_html", "wgallowexternalimages": "allow_external_images", "wgmaxtoclevel": "max_toc_level",
    "wglinkholderbatchsize": "link_holder_batch_size", "wgenableuploads": "enable_uploads",
    "wgallowexternalimagesfrom": "allow_external_images_from", "wgenableimagewhitelist": "enable_image_whitelist",
    "wgexternallinktarget": "external_link_target", "wgnofollowlinks": "no_follow_links",
    "wgfragmentmode": "fragment_mode", "wgallowimagetag": "allow_image_tag", "wgcapitallinks": "capital_links",
    "wgmaxtemplatedepth": "max_template_depth", "wgmaxppnodecount": "max_pp_node_count",
    "wgmaxppexpanddepth": "max_pp_expand_depth", "wgexpensiveparserfunctionlimit": "expensive_parser_function_limit",
}


def _php_value(text: str):
    """A PHP or JSON literal of a test setting: true/false/null, numbers, quoted strings, [ ... ] and { ... }."""
    import json

    text = text.strip().rstrip(";")
    low = text.lower()
    if low in ("true", "false", "null"):
        return {"true": True, "false": False, "null": None}[low]
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if text[:1] in "\"'" and text[-1:] == text[:1]:
        return text[1:-1]
    if text.startswith(("[", "{")):
        try:
            return json.loads(text)
        except ValueError:
            items = [_php_value(x) for x in re.findall(r"'[^']*'|\"[^\"]*\"|[^,\[\]\s]+", text)]
            return tuple(items)
    return text


def test_config(test: ParserTest):
    """The settings a test runs with: the parser-test defaults, its options and its !! config section."""
    from .config import TEST

    changes: dict[str, object] = {}
    settings = {k: v for k, v in test.options.items() if k.startswith("wg") or k == "thumbsize"}
    for line in test.sections.get("config", "").split("\n"):
        if "=" in line:
            name, _, value = line.partition("=")
            settings[name.strip().lower()] = _php_value(value)
    for name, value in settings.items():
        if isinstance(value, str) and name != "thumbsize":
            value = _php_value(value)
        if name == "wgenablemagiclinks":
            changes["enable_magic_links"] = {"ISBN": True, "PMID": True, "RFC": True, **(value or {})}
        elif name == "thumbsize":
            changes["thumb_limits"] = (0, 0, 0, 0, 0, int(value))
        elif name in _SETTINGS:
            if isinstance(value, list):
                value = tuple(value)
            changes[_SETTINGS[name]] = value
    return TEST.with_(**changes) if changes else TEST


def run_test(test: ParserTest, articles: dict[str, str]) -> Result:
    from .parser import parse
    from .site import test_site

    title = test.options.get("title", DEFAULT_TITLE)
    config = test_config(test)
    try:
        actual = parse(test.wikitext or "", title=title if isinstance(title, str) else DEFAULT_TITLE, pages=articles,
                       config=config, site=test_site(subpages="subpage" in test.options, config=config))
    except Exception as e:  # noqa: BLE001 - a crash is a failed test, reported with the rest
        return Result(test, False, error=f"{type(e).__name__}: {e}")
    actual = re.sub(r"\s+$", "", actual)  # as ParserTestRunner does
    return Result(test, actual == test.legacy_html, actual)


def run(path: Path = TEST_FILE, name_filter: str = "") -> tuple[list[Result], dict[str, int]]:
    data = read(path)
    results, skipped = [], {}
    for test in data.tests:
        reason = test.skip_reason()
        if reason:
            key = reason.split(",")[0]
            skipped[key] = skipped.get(key, 0) + 1
            continue
        if name_filter and name_filter.lower() not in test.name.lower():
            continue
        results.append(run_test(test, data.articles))
    return results, skipped


def load_passing(path: Path = PASSING_FILE) -> set[str]:
    return set(path.read_text(encoding="utf-8").splitlines()) if path.exists() else set()


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filter", default="", help="only tests whose name contains this")
    ap.add_argument("--show", type=int, default=0, help="print this many failures")
    ap.add_argument("--accept", action="store_true", help=f"write the passing tests to {PASSING_FILE.name}")
    a = ap.parse_args(argv)

    results, skipped = run(name_filter=a.filter)
    passed = [r for r in results if r.passed]
    known = load_passing()
    regressed = sorted(known - {r.test.name for r in passed} & {r.test.name for r in results})
    print(f"{len(passed)} of {len(results)} legacy parser tests pass; skipped: "
          + ", ".join(f"{k} {v}" for k, v in sorted(skipped.items())))
    if regressed:
        print(f"{len(regressed)} tests that passed before fail now: " + "; ".join(regressed[:10]))
    shown = 0
    for r in results:
        if r.passed or shown >= a.show:
            continue
        shown += 1
        print(f"\n--- {r.test.name} (line {r.test.line})\n[wikitext]\n{r.test.wikitext}\n[expected]\n{r.test.legacy_html}")
        print(f"[actual]\n{r.actual}" if not r.error else f"[error] {r.error}")
    if a.accept:
        if a.filter:
            print("--accept needs the full run (no --filter)")
            return 1
        PASSING_FILE.write_text("".join(n + "\n" for n in sorted(r.test.name for r in passed)), encoding="utf-8",
                                newline="\n")
        print(f"wrote {len(passed)} names to {PASSING_FILE}")
    return 1 if regressed else 0


if __name__ == "__main__":
    sys.exit(main())
