# biwiki — дзеркало Arma 3 Scripting Reference

Завантажує всі сторінки з
[Category:Arma 3: Scripting Commands](https://community.bistudio.com/wiki/Category:Arma_3:_Scripting_Commands) та
[Category:Arma 3: Functions](https://community.bistudio.com/wiki/Category:Arma_3:_Functions)
з BI Community Wiki і конвертує їх у **Markdown** (для людей/LLM) та **JSON** (для агентів і інструментів).

## Як це працює

Вікі стоїть за Cloudflare managed challenge, тому звичайні HTTP-клієнти отримують 403.
`sync` запускає ваш встановлений Google Chrome через [patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright),
проходить перевірку і далі викликає MediaWiki API (`/wikidata/api.php`) через `fetch()` усередині сторінки —
по 50 сторінок вікітексту за запит (~110 запитів на все). Сирий вікітекст кешується в `data/raw/*.json`;
повторний `sync` докачує лише сторінки зі зміненим `revid`.

Потім `build` розбирає шаблон `{{RV}}` кожної сторінки (`mwparserfromhell`) у структуровані поля
та генерує дзеркало в `out/`.

Сайт: **https://a3ref.github.io/**

## Деплой

У репозиторії зберігаються лише код і сирий вікітекст (`data/raw/*.json`, ≈6 МБ).
Усе в `out/` генерується під час деплою і не комітиться.

Workflow `.github/workflows/site.yml`:

- **щодня о 04:17 UTC** — `sync` (справжній Chrome у `xvfb`), коміт змінених `data/raw`, збірка й деплой на GitHub Pages;
  якщо на вікі нічого не змінилось, деплой пропускається;
- **push у `main`** — лише збірка й деплой (наприклад, після змін у парсері чи дизайні);
- **ручний запуск** (Actions → Sync and deploy → Run workflow), з опцією `full` для повного перезавантаження.

Якщо Cloudflare не пропускає раннер GitHub, синхронізацію можна запускати локально
(`python -m biwiki sync`, потім `git commit data/raw && git push`) — push сам запустить деплой.

## Встановлення

Потрібні Python 3.10+ і встановлений Google Chrome.

```sh
pip install -r requirements.txt
```

## Використання

```sh
python -m biwiki update            # sync + build (відкриє вікно Chrome на ~1 хв)
python -m biwiki update --hidden   # те саме, вікно Chrome за межами екрана
python -m biwiki sync --full       # перекачати все, ігноруючи кеш
python -m biwiki build             # лише перегенерувати out/ з кешу (≈20 с)
python -m biwiki serve --port 8000 # віддати out/ по HTTP (text/markdown, application/json)
```

`--only commands` / `--only functions` обмежує роботу однією категорією.
Справжній headless-режим Cloudflare блокує; якщо з'явиться чекбокс — запустіть без `--hidden` і клацніть його.

## Що генерується (`out/`)

| Файл | Призначення |
|---|---|
| `index.html` | **сайт для людей**: головна з пошуком, групи, сторінки команд/функцій |
| `index.md` | головна сторінка дзеркала в Markdown |
| `commands/index.md`, `functions/index.md` | списки, згруповані за групами команд |
| `commands/<name>.md`, `functions/<name>.md` | сторінка з YAML front-matter, описом, синтаксисами, параметрами, прикладами, нотатками спільноти; посилання між командами/функціями ведуть на локальні файли |
| `commands/<name>.json`, `functions/<name>.json` | та сама сторінка структуровано |
| `commands/<name>.html`, `functions/<name>.html` | та сама сторінка як HTML |
| `assets/` | стилі, скрипт і пошуковий індекс HTML-версії |
| `commands.json`, `functions.json` | усі записи однієї категорії одним файлом |
| `index.json` | легкий індекс для агентів: ім'я, синтаксиси, короткий опис, групи, локальність, шляхи до файлів |
| `llms.txt` | індекс у форматі [llms.txt](https://llmstxt.org/) |

Імена файлів: пробіли → `_`, інші небезпечні символи → `~XX` (hex), напр. `a != b` → `a_~21~3D_b.md`.
Функції називаються як у скриптах: `BIS_fnc_spawnGroup.md`. Точні шляхи є в `index.json`.

### Схема JSON-запису

```jsonc
{
  "name": "createVehicle",            // як пишеться в коді (BIS_fnc_... для функцій)
  "title": "createVehicle",           // заголовок сторінки вікі
  "type": "command",                  // або "function"
  "url": "https://community.bistudio.com/wiki/createVehicle",
  "revid": 377509, "updated": "2026-01-02T06:50:13Z",
  "groups": ["Object Manipulation"],
  "games": [{"game": "ofp", "name": "Operation Flashpoint", "version": "1.34"}, ...],
  "since": {...},                      // перша гра, де з'явилось
  "arma3_since": "0.50",
  "branch": null,                      // "dev" / "diag" для команд лише з dev/diag-збірок
  "locality": {"argument": "global", "effect": "global", "server_exec": false},
  "exec": null,                        // для функцій: "spawn" / "call"
  "description": "markdown",
  "syntaxes": [{
    "syntax": "type createVehicle position",
    "since": null, "effect": null, "exec": null,
    "params": [{
      "name": "type", "type": "String", "optional": false, "default": null,
      "description": "vehicle/object className", "since": null,
      "text": "повний текст параметра (markdown)"
    }],
    "returns": {"type": "Object", "description": null, "text": "markdown"}
  }],
  "examples": [{"text": "markdown", "code": ["сирий SQF"]}],
  "multiplayer": null, "problems": null,
  "aliases": [], "see_also": ["createVehicleLocal", ...],
  "notes": [{"user": "MrSanchez", "date": "2015-08-22T13:04:00Z", "text": "markdown"}],
  "categories": [...]
}
```

`name`/`type`/`optional`/`default` у параметрах витягуються евристично з тексту вікі
(`name: Type - (Optional, default x) опис`); поле `text` завжди містить оригінал без втрат.
У JSON посилання подані простим текстом (економія токенів), у `.md` — повноцінними посиланнями.

## HTML-версія

Статичний сайт без збирача і без залежностей у JS: відкривається з `python -m biwiki serve`
(http://127.0.0.1:8000/index.html) або просто подвійним кліком по `out/index.html`.

- пошук по всіх командах і функціях (`/` — фокус, стрілки, Enter);
- підсвітка SQF, де кожна команда/функція в коді — посилання на свою сторінку;
- плашки Note/Important/Warning, бейджі локальності (заповнений — global, контурний — local), версії;
- зміст сторінки, кнопка «Copy» на блоках коду, світла/темна тема за системними налаштуваннями, мобільна верстка;
- шапка кожної сторінки — «топокарта», згенерована з назви команди.

Шрифти (Barlow, JetBrains Mono) підвантажуються з Google Fonts; офлайн використовуються системні.

## Структура коду

- `biwiki/fetch.py` — браузерна сесія, MediaWiki API, інкрементальний кеш
- `biwiki/wikitext.py` — вікітекст → Markdown (посилання, списки, таблиці, `<sqf>`, `{{Feature}}`, `{{GVI}}`, `{{hl}}`, …)
- `biwiki/parse.py` — шаблон `{{RV}}` → запис
- `biwiki/render.py` — запис файлів дзеркала та індексів
- `biwiki/site.py`, `biwiki/assets/` — HTML-версія (markdown-it-py, підсвітка SQF, шаблони сторінок)

Вміст належить авторам BI Community Wiki; кожна згенерована сторінка містить посилання на джерело та номер ревізії.
