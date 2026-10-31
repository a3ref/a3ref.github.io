"""Highlighting of JSON, TOML and shell blocks, and the caption a block's title becomes."""
from __future__ import annotations

import unittest

from biwiki.site import CodeLinker


class HighlightTest(unittest.TestCase):
    def setUp(self):
        self.link = CodeLinker({})

    def test_json(self):
        out = self.link('{"a": [1, -2.5e3], "b": "x: y", "c": null}', "json", "")
        self.assertIn('<span class="t-key">&quot;a&quot;</span>', out)
        self.assertIn('<span class="t-number">-2.5e3</span>', out)
        self.assertIn('<span class="t-string">&quot;x: y&quot;</span>', out, "a colon inside a value is no key")
        self.assertIn('<span class="t-literal">null</span>', out)

    def test_json_array_line_is_no_toml_section(self):
        self.assertNotIn("t-section", self.link('{\n  "args":\n  ["-y", "x"]\n}', "json", ""))

    def test_toml(self):
        out = self.link('# c\n[mcp_servers.a3ref]\ncommand = "npx"\nenabled = true\n', "toml", "")
        self.assertIn('<span class="t-comment"># c</span>', out)
        self.assertIn('<span class="t-section">[mcp_servers.a3ref]</span>', out)
        self.assertIn('<span class="t-key">command</span>', out)
        self.assertIn('<span class="t-literal">true</span>', out)

    def test_shell(self):
        out = self.link("codex mcp add a3ref -- npx -y github:a3ref/mcp\n", "sh", "")
        self.assertTrue(out.startswith('<pre class="code" tabindex="0"><code class="language-sh"><span class="t-prog">codex</span>'))
        self.assertIn('<span class="t-flag">-y</span> github:a3ref/mcp', out)

    def test_title(self):
        out = self.link("{}", "json", 'title="~/.cursor/mcp.json"')
        self.assertIn('data-title="~/.cursor/mcp.json"', out)
        self.assertNotIn("data-title", self.link("{}", "json", ""))


if __name__ == "__main__":
    unittest.main()
