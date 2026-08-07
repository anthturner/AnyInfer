@echo off
rem Run the checkout's task runner, forwarding all arguments: `.\workspace <verb> [...]`.
rem The installed `workspace` console script is a copy that can go stale (see
rem _warn_if_shadowed in workspace.py); this wrapper always executes the file beside it.
rem A repo-local .venv wins over whatever `python` happens to be on PATH.
setlocal
set "_root=%~dp0"
if exist "%_root%.venv\Scripts\python.exe" (
  "%_root%.venv\Scripts\python.exe" "%_root%workspace.py" %*
) else (
  python "%_root%workspace.py" %*
)
exit /b %errorlevel%
