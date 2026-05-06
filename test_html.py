from pygments import highlight
from pygments.lexers import JsonLexer
from pygments.formatters import HtmlFormatter

text = '{"key": "value"}'
formatter = HtmlFormatter(nowrap=False, style='monokai', noclasses=True)
highlighted = highlight(text, JsonLexer(), formatter)
print(highlighted)
