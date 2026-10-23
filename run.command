#!/bin/bash
# Двойной клик в Finder: делает answers.jsonl для data/test_predictions.jsonl.
cd "$(dirname "$0")" || exit 1
PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
    echo "Python не найден. Установите Python 3.10+ с https://www.python.org/downloads/"
else
    "$PYTHON" postprocess.py data/test_predictions.jsonl answers.jsonl && echo "Готово: answers.jsonl"
fi
echo
read -r -p "Нажмите Enter, чтобы закрыть окно"
