@echo off
cd /d "%~dp0"
echo Jarvis receptionist
echo   1 typed, no voice
echo   2 typed + British neural voice
echo   3 hold Home (base whisper, more accurate) + British neural
echo   4 hold Home, grok-4.6 + base whisper
echo   5 hold Home + old Windows David/Hazel (offline)
echo   6 hold Home, tiny whisper (faster, sloppier)
echo   7 always-on mic (base whisper) + British neural. Home still PTT.
echo   8 like 7, but only after you say Jarvis (or hey Jarvis).
echo   m list microphones
set /p c=choice:
echo Leave this window open. Ctrl+C stops Jarvis (do not use it to copy text).
if "%c%"=="1" .venv\Scripts\python talk.py --brain agent --model grok-4.6 --stt none --tts none
if "%c%"=="2" .venv\Scripts\python talk.py --brain agent --model grok-4.6 --stt none --tts edge
if "%c%"=="3" .venv\Scripts\python talk.py --brain agent --model grok-4.6 --stt base --tts edge
if "%c%"=="4" .venv\Scripts\python talk.py --brain agent --model grok-4.6 --stt base --tts edge
if "%c%"=="5" .venv\Scripts\python talk.py --brain agent --model grok-4.6 --stt base --tts sapi
if "%c%"=="6" .venv\Scripts\python talk.py --brain agent --model grok-4.6 --stt tiny --tts edge
if "%c%"=="7" .venv\Scripts\python talk.py --brain agent --model grok-4.6 --stt base --tts edge --listen
if "%c%"=="8" .venv\Scripts\python talk.py --brain agent --model grok-4.6 --stt base --tts edge --wake
if /I "%c%"=="m" .venv\Scripts\python talk.py --list-mics
if errorlevel 1 exit /b %errorlevel%
pause
