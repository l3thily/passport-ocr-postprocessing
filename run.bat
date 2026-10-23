@echo off
rem Двойной клик в Проводнике: делает answers.jsonl для data\test_predictions.jsonl.
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% postprocess.py data\test_predictions.jsonl answers.jsonl && echo Готово: answers.jsonl
echo.
pause
