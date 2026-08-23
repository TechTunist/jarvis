@echo off
cd /d "%~dp0"
echo Jarvis receptionist
echo   1 typed, no voice
echo   2 typed + British neural voice
echo   3 hold Home (base whisper, more accurate) + British neural
echo   4 hold Home, grok-4.6 + base whisper
echo   5 hold Home + old Windows David/Hazel (offline)
echo   6 hold Home, tiny whisper (faster, sloppier)
echo   m list microphones
set /p c=choice:
if "%c%"=="1" .venv\Scripts\python talk.py --brain agent --model grok-4.5 --stt none --tts none
if "%c%"=="2" .venv\Scripts\python talk.py --brain agent --model grok-4.5 --stt none --tts edge
if "%c%"=="3" .venv\Scripts\python talk.py --brain agent --model grok-4.5 --stt base --tts edge
if "%c%"=="4" .venv\Scripts\python talk.py --brain agent --model grok-4.6 --stt base --tts edge
if "%c%"=="5" .venv\Scripts\python talk.py --brain agent --model grok-4.5 --stt base --tts sapi
if "%c%"=="6" .venv\Scripts\python talk.py --brain agent --model grok-4.5 --stt tiny --tts edge
if /I "%c%"=="m" .venv\Scripts\python talk.py --list-mics
pause
