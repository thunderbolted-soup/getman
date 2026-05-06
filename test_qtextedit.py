import sys
from PySide6.QtWidgets import QApplication, QTextEdit
from pygments import highlight
from pygments.lexers import JsonLexer
from pygments.formatters import HtmlFormatter

app = QApplication(sys.argv)
edit = QTextEdit()
text = '{\n  "key": "value",\n  "num": 123\n}'
formatter = HtmlFormatter(nowrap=False, style='monokai', noclasses=True)
highlighted = highlight(text, JsonLexer(), formatter)
print(highlighted)

html = f"""
<html>
<body style="background-color: #272822; color: #f8f8f2; margin: 0; padding: 10px; font-family: 'Courier New';">
    {highlighted}
</body>
</html>
"""
edit.setHtml(html)
print("Plain text output from QTextEdit:")
print(edit.toPlainText())
