# Getman: контекст для AI-агента

## Обзор проекта
Getman — десктопный HTTP-клиент для локальной работы: быстрая отладка API без аккаунтов и облака.
Вкладки, коллекции с папками, окружения и переменные, история, автодополнение, импорт из
Postman / Insomnia / OpenAPI / HAR / .http / cURL, Python-скрипты до и после запроса.

**Жёсткое требование: ≤ 50 МБ ОЗУ** (приватная рабочая память процесса, как в Диспетчере задач).
Проверка: `python tools/memcheck.py --budget 50` (в CI — на windows-latest).

## Техстек
- **Python 3.11+, PySide6-Essentials** (QtCore/Gui/Widgets/Network). Других обязательных зависимостей нет.
- **HTTP:** `QNetworkAccessManager` (QtNetwork) — асинхронно в UI-потоке, без потоков/asyncio. Отмена = `abort()`.
- **Подсветка:** собственные `QSyntaxHighlighter` (JSON/XML/Python/GraphQL), цвета Monokai. Без Pygments.
- **Хранение:** JSON-файлы в `data/` (рядом с приложением; если папка только для чтения — профиль пользователя).
  Путь можно переопределить через `GETMAN_DATA_DIR`.
- **PyYAML** — опционально, импортируется лениво только для YAML-импорта.

## Архитектура
- `main.py` — точка входа.
- `core/` — логика без UI (кроме `http_client.py`), покрыта тестами:
    - `models.py` — модель данных (обычные dict): коллекция → папки → запросы, `normalize_*`.
    - `request_preparer.py` [CRITICAL] — `prepare_request()`: pre-request скрипт, `{{переменные}}` везде,
      path-переменные `:id`, авторизация с наследованием (запрос → папки → коллекция), заголовки по умолчанию,
      кодирование тела. `generate_curl()` для экспорта.
    - `http_client.py` — `HttpClient.send(prep) -> RequestJob` (сигналы `finished/failed/cancelled`),
      человекочитаемые сетевые ошибки.
    - `variables.py` — `resolve()`/`apply_env`, слои: local > environment > collection > globals, `{{$guid}}` и др.
    - `scripting.py` — Python-скрипты (`env`, `variables`, `request`/`response`, `test()`, `log()`).
    - `importers/` — автоопределение формата (`parse_text`, `parse_file`) и конвертеры; экспорт в Postman v2.1.
    - `collection.py`, `environment.py`, `history.py`, `settings.py`, `session.py` — хранилища.
      Старые данные (Postman-формат коллекций Getman 1.x) мигрируются при загрузке.
    - `completion.py` — индекс автодополнения (URL, заголовки, параметры из истории и коллекций).
- `ui/`:
    - `main_window.py` — вкладки (`TabDoc` — только данные), отправка/сохранение, сессия, горячие клавиши.
    - `request_editor.py` — **один** редактор на все вкладки; разделы строятся лениво при первом открытии.
    - `response_view.py` — ответ: Pretty/Raw/Preview, заголовки, cookies, консоль (что реально ушло + скрипты).
    - `sidebar.py` — дерево коллекций (drag&drop, F2, контекстные меню), история по датам, фильтр с debounce.
    - `fields.py` — `SmartLineEdit`: подсветка `{{var}}`, подсказка значения при наведении, автодополнение.
    - `kv_table.py` — таблица ключ/значение (+ bulk edit), `code_editor.py` — редактор кода + поиск.
    - `dialogs.py`, `import_dialog.py`, `palette.py` (Ctrl+P) — диалоги; `theme.py` — токены цветов и QSS.

## Правила кодинга
- **Подготовка запроса:** никогда не дублировать логику в UI — только `prepare_request()` (и для Send, и для cURL).
- **Сеть:** только через `HttpClient` (QtNetwork). Не блокировать UI-поток, не добавлять потоки без нужды.
- **Переменные:** `{{variable}}` должны работать во всех полях запроса (URL, параметры, заголовки, тело, auth).
- **Память (бюджет 50 МБ):**
    - не добавлять тяжёлые зависимости (httpx, pygments, prance и т.п.); тяжёлые модули импортировать лениво;
    - виджеты, которые видны не сразу, создавать лениво (см. `RequestEditor._ensure`, `ResponseView._page`);
    - диалоги и меню после `exec()` удалять (`deleteLater()` / `WA_DeleteOnClose`), `RequestJob` удаляет себя сам;
    - после изменений прогонять `python tools/memcheck.py --budget 50`.
- **UI:**
    - `QSplitter` для адаптивности; поиск/фильтры — с debounce через `QTimer`;
    - горячие клавиши: Ctrl+T, Ctrl+W, Ctrl+S, Ctrl+Enter, Ctrl+L, Ctrl+P, Ctrl+E, Ctrl+I, Ctrl+F, Esc (отмена);
    - ошибки валидации — через динамическое свойство Qt `setProperty("error", "true")`;
    - цвета — только из `ui/theme.py` (две темы: dark/light).

## Команды
```bash
pip install -r requirements.txt          # зависимости приложения
python main.py                           # запуск
pip install -r requirements-dev.txt      # pytest, psutil
python -m pytest -q tests                # тесты (UI-тесты работают с QT_QPA_PLATFORM=offscreen)
python tools/memcheck.py --budget 50     # проверка бюджета памяти
pyinstaller Getman.spec                  # сборка в один файл
cat data/app.log                         # лог
```

## Важно
- **Никаких облаков:** всё строго локально.
- **Экспорт cURL** учитывает окружение и изменения из pre-request скрипта (тот же `prepare_request`).
- **UX:** кнопка «Send» превращается в «Cancel» во время запроса; несохранённые вкладки переживают перезапуск.
- **Response:** JSON форматируется автоматически, подсветка Monokai.
- **Network:** сетевые ошибки — человекочитаемые (`core/http_client.py: human_error`).
