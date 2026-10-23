# Постобработка OCR паспорта РФ

Публичный репозиторий для сдачи: https://github.com/l3thily/passport-ocr-postprocessing

Два варианта решения, отчёт и обоснование прогноза — [REPORT.md](REPORT.md):

- **сбалансированный (основной)**, `answers.jsonl`: 868 из 2000 принято, прогноз ~4.6 с ошибкой;
- **нулевой**, `answers_zero.jsonl`: 306 принято, прогноз ~0.5 с ошибкой (шанс ровно нуля ~53%).

## Запуск

Стандартная библиотека Python 3.10+, CPU, без установки пакетов и сети:

```sh
python3 postprocess.py data/test_predictions.jsonl answers.jsonl
python3 postprocess.py data/test_predictions.jsonl answers_zero.jsonl --variant zero
```

Инференсу нужны только `core.py`, `postprocess.py`, `model.json` и входной файл. Train и его разметку он не читает.

## Воспроизведение

```sh
python3 train.py      # CV и прогноз обоих вариантов, model.json, оба файла ответов, metrics.json
python3 tests.py      # 37 тестов: правила, реальные документы, порчи МЧЗ, инварианты ответов
python3 verify.py     # сверка ответов, метрик и поведения CLI -> verification.json
python3 evaluate.py validation_answers.jsonl data/train_labels.jsonl
```

`train.py` делит train на пять частей по SHA-256(doc_id). В каждой части словарь ведомств строится без проверяемых строк, ответы сохраняются в `validation_answers.jsonl`. Затем на всём train собирается финальный `model.json` и заново пишутся ответы на test. Пороги уверенности заданы в `train.py` и выбраны по всему train (обоснование в REPORT.md).

## Файлы

- `postprocess.py`, `core.py` — инференс; `model.json` — пороги обоих вариантов и словарь написаний ведомств по коду подразделения.
- `answers.jsonl`, `answers_zero.jsonl` — ответы на 2000 документов test для двух вариантов.
- `train.py`, `tests.py`, `verify.py` — воспроизведение и проверки; `metrics.json`, `verification.json` — их результаты.
- `run-isolated.sh`, `ISOLATION.md`, `audit_security.py`, `security_checks.json` — запуск в песочнице macOS из прошлой версии.
- `experiments/` — прежние версии решения (79 и 86 принятых) с их отчётами и аудитом; при запуске не используются.
- `data/`, `reference/`, `TASK.md`, `evaluate.py` — неизменённые материалы задания. Справочник `reference/subdivisions.csv` текущий инференс не использует.

`train_answers.jsonl` и `validation_answers.jsonl` исключены из Git: их создаёт `train.py`. `SHA256SUMS.json` содержит хеши файлов репозитория, кроме самого манифеста.
