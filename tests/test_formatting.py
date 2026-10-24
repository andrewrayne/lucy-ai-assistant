from app.bot.formatting import markdown_to_html, split_message


def test_basic_markdown():
    assert markdown_to_html("**bold** and *it*") == "<b>bold</b> and <i>it</i>"
    assert markdown_to_html("use `x < y`") == "use <code>x &lt; y</code>"
    assert markdown_to_html("[site](https://a.com)") == '<a href="https://a.com">site</a>'


def test_html_is_escaped_and_code_untouched():
    assert markdown_to_html("1 < 2 & 3 > 2") == "1 &lt; 2 &amp; 3 &gt; 2"
    assert markdown_to_html("```py\nprint('**x**')\n```") == "<pre>print('**x**')</pre>"


def test_lists_and_headings():
    assert markdown_to_html("# Title\n- one\n* two") == "<b>Title</b>\n• one\n• two"


def test_split_long_message():
    text = ("a" * 3000 + "\n\n") * 3
    parts = split_message(text, limit=4096)
    assert len(parts) == 3 and all(len(p) <= 4096 for p in parts)
