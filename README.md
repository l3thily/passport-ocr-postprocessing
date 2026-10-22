# Постобработка OCR паспорта РФ

Приватный репозиторий для сдачи: https://github.com/l3thily/passport-ocr-postprocessing

Проверенная версия: 79 accept, 1921 reject. Это осторожный baseline с низким покрытием; нулевая ошибка скрытого test не доказана. Краткий отчёт — [REPORT.md](REPORT.md), результаты повторного аудита — [AUDIT.md](AUDIT.md).

## Запуск

Стандартная библиотека Python 3.10+, CPU, без установки пакетов и сети:

```sh
python3 postprocess.py data/test_predictions.jsonl answers.jsonl
```

Изолированный запуск на macOS:

```sh
sh run-isolated.sh data/test_predictions.jsonl answers.jsonl
```

По умолчанию используется /opt/homebrew/bin/python3. Другой установленный интерпретатор можно задать переменной OCR_PYTHON. Вход и выход должны находиться внутри папки решения. Подробности ограничений и проверок — [ISOLATION.md](ISOLATION.md).

## Воспроизведение проверки

```sh
python3 train.py
python3 tests.py
python3 verify.py
python3 evaluate.py validation_answers.jsonl data/train_labels.jsonl
```

Эти обычные команды предназначены для доверенной среды; сами по себе они не включают песочницу. В проведённом аудите они запускались явно через sandbox-exec с очищенным окружением и Python -I -S.

train.py повторяет пять разбиений по SHA-256(doc_id), обучает словари внутри каждого, сохраняет validation_answers.jsonl, затем финальный model.json и ответы. **Проверочные данные ранее использовались для уточнения общих правил, поэтому итоговая CV не является независимой оценкой качества.** verify.py отдельно сверяет выходы, даты и поведение CLI. Инференс не читает train или его разметку; это проверено в отдельной папке без обучающих файлов.

## Файлы

- postprocess.py, core.py — инференс; model.json — готовые словари ведомств и пороги.
- answers.jsonl — 79 принятых из 2000 тестовых документов.
- train.py, tests.py, verify.py — воспроизведение и проверки.
- metrics.json, verification.json — метрики и подтверждения проверок с хешами кода.
- security_checks.json, audit_security.py — результаты и код проверок ограничений ОС; audit_security.py должен запускаться внутри песочницы с безвредным внешним контрольным каталогом.
- review_changes.json, experiments/ — изменения решений и история результатов.
- data/, reference/, TASK.md, evaluate.py — неизменённые материалы задания.

Исходные данные включены в приватный репозиторий, поэтому команда запуска работает сразу после клонирования. train_answers.jsonl и validation_answers.jsonl исключены из Git: их создаёт train.py. Инференсу нужны только код, model.json, reference/subdivisions.csv и переданный входной файл. Справочник распространяется с исходным указанием CC BY-SA 4.0, см. reference/SOURCE.txt.

SHA256SUMS.json содержит хеши файлов репозитория (кроме самого манифеста). Для сдачи передайте ссылку на приватный репозиторий и предоставьте проверяющему доступ. Основной отчёт — REPORT.md; AUDIT.md и ISOLATION.md содержат дополнительные технические проверки. experiments/ хранит исторические версии, которые не используются при запуске.
