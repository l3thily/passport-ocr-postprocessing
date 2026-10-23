# Постобработка OCR паспорта РФ

Публичный репозиторий для сдачи: https://github.com/l3thily/passport-ocr-postprocessing

Одно решение с тремя порогами строгости. Сводный отчёт и прогноз лежат в [REPORT.md](REPORT.md), подробное описание каждого варианта — в README его папки.

| Вариант | Папка | Принято на test | Ожидаемо ошибок |
|---|---|---|---|
| `zero` | [variants/zero](variants/zero/README.md) | 306 (15.3%) | 0.5 |
| `balanced`, основной | [variants/balanced](variants/balanced/README.md) | 868 (43.4%) | 4.6 |
| `max50` | [variants/max50](variants/max50/README.md) | 1001 (50.1%) | 7.8 |

`answers.jsonl` в корне совпадает с `variants/balanced/answers.jsonl`.

## Запуск

Стандартная библиотека Python 3.10+, CPU, без установки пакетов и сети:

```sh
python3 postprocess.py data/test_predictions.jsonl answers.jsonl
python3 postprocess.py data/test_predictions.jsonl answers.jsonl --variant zero   # или balanced, max50
```

Без терминала: двойной клик по `run.command` на Mac или `run.bat` на Windows. Файл делает то же, что первая команда, и пишет `answers.jsonl` рядом. macOS при первом запуске скачанного скрипта может его заблокировать: тогда правый клик → «Открыть» → «Открыть».

Инференсу нужны только `core.py`, `postprocess.py`, `model.json` и входной файл. Train и его разметку он не читает.

## Воспроизведение

```sh
python3 train.py      # CV и прогноз всех вариантов, model.json, файлы ответов, metrics.json
python3 tests.py      # 37 тестов: правила, реальные документы, порчи МЧЗ, инварианты ответов
python3 verify.py     # сверка ответов, метрик и поведения CLI -> verification.json
python3 evaluate.py validation_answers.jsonl data/train_labels.jsonl
```

`train.py` делит train на пять частей по SHA-256(doc_id). В каждой части словарь ведомств строится без проверяемых строк, ответы сохраняются в `validation_answers.jsonl`. Затем на всём train собирается финальный `model.json` и заново пишутся ответы на test. Пороги уверенности заданы в `train.py` и выбраны по всему train (обоснование в REPORT.md).

## Файлы

- `postprocess.py`, `core.py` — инференс; `model.json` — пороги всех вариантов и словарь написаний ведомств по коду подразделения.
- `answers.jsonl` — основной ответ на 2000 документов test; `variants/<имя>/` — ответы и описание каждого варианта.
- `train.py`, `tests.py`, `verify.py` — воспроизведение и проверки; `metrics.json`, `verification.json` — их результаты.
- `run-isolated.sh`, `ISOLATION.md`, `audit_security.py`, `security_checks.json` — запуск в песочнице macOS из прошлой версии.
- `experiments/` — прежние версии решения (79 и 86 принятых) с их отчётами и аудитом; при запуске не используются.
- `data/`, `reference/`, `TASK.md`, `evaluate.py` — неизменённые материалы задания. Справочник `reference/subdivisions.csv` текущий инференс не использует.

`train_answers.jsonl` и `validation_answers.jsonl` исключены из Git: их создаёт `train.py`. `SHA256SUMS.json` содержит хеши файлов репозитория, кроме самого манифеста.
