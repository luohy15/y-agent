"""Unit tests for storage.util.markdown_to_telegram_html.

The markdown -> Telegram-HTML conversion the webhook/send path relies on. Pure
string transform: no DB, no network. Covers the supported-tag mappings and the
escaping that keeps Telegram's restricted HTML subset valid.
"""

import unittest

from storage.util import markdown_to_telegram_html as md


class MarkdownToTelegramHtmlTest(unittest.TestCase):
    def test_bold_and_italic(self):
        self.assertEqual(md("**bold**"), "<b>bold</b>")
        self.assertEqual(md("__bold__"), "<b>bold</b>")
        self.assertEqual(md("*it*"), "<i>it</i>")
        self.assertEqual(md("~~gone~~"), "<s>gone</s>")

    def test_heading_becomes_bold(self):
        self.assertEqual(md("# Title"), "<b>Title</b>")
        self.assertEqual(md("### Sub"), "<b>Sub</b>")

    def test_link_conversion(self):
        self.assertEqual(md("[label](https://x.com)"), '<a href="https://x.com">label</a>')

    def test_inline_code_is_escaped_and_wrapped(self):
        self.assertEqual(md("`a < b`"), "<code>a &lt; b</code>")

    def test_fenced_code_block_preserved_and_escaped(self):
        out = md("```python\nif a < b:\n    pass\n```")
        self.assertIn("<pre>", out)
        self.assertIn("if a &lt; b:", out)
        # Markdown inside a fence must not be reinterpreted.
        self.assertNotIn("<b>", md("```\n**not bold**\n```"))

    def test_raw_angle_brackets_escaped(self):
        self.assertEqual(md("1 < 2 > 0"), "1 &lt; 2 &gt; 0")

    def test_bullet_list_becomes_dots(self):
        self.assertEqual(md("- one\n- two"), "• one\n• two")

    def test_checkboxes(self):
        self.assertEqual(md("- [x] done"), "✅ done")
        self.assertEqual(md("- [ ] todo"), "⬜ todo")

    def test_underscore_inside_word_not_italicized(self):
        # snake_case identifiers must survive intact.
        self.assertEqual(md("send_chat_message"), "send_chat_message")


if __name__ == "__main__":
    unittest.main()
