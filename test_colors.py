import sys
from PySide6.QtWidgets import QApplication, QTextEdit
from pygments import highlight
from pygments.lexers import JsonLexer
from pygments.formatters import HtmlFormatter

app = QApplication(sys.argv)
edit = QTextEdit()
text = '{\n  "key": "value",\n  "num": 123\n}'
formatter = HtmlFormatter(nowrap=True, style='monokai', noclasses=True)
highlighted = highlight(text, JsonLexer(), formatter)

html = f"""
<html>
<body style="background-color: #272822; color: #f8f8f2; margin: 0; padding: 10px; font-family: 'Courier New';">
    <pre style="white-space: pre-wrap; margin: 0;">{highlighted}</pre>
</body>
</html>
"""
edit.setHtml(html)
edit.show()

# Instead of executing app.exec(), let's just grab a screenshot of the widget
pixmap = edit.grab()
pixmap.save('test_colors.png')
print("Saved screenshot to test_colors.png")
