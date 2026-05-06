import sys
from PySide6.QtWidgets import QApplication, QTextEdit
from pygments import highlight
from pygments.lexers import JsonLexer
from pygments.formatters import HtmlFormatter

app = QApplication(sys.argv)
edit = QTextEdit()
text = '{"key": 123}'

formatter2 = HtmlFormatter(nowrap=True, style='monokai', noclasses=True)
html2 = f'<pre>{highlight(text, JsonLexer(), formatter2)}</pre>'
edit.setHtml(html2)
print("HTML:")
print(edit.toHtml())
