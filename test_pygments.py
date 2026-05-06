from pygments import highlight
from pygments.lexers import JsonLexer
from pygments.formatters import HtmlFormatter

text = '{"key": "value", "num": 123}'
formatter = HtmlFormatter(nowrap=True, style='monokai', noclasses=True)
print(highlight(text, JsonLexer(), formatter))
