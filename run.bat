@echo off
setlocal
set "PROJECT_ROOT=%~dp0"
set "PYTHON=C:\venvs\p313\Scripts\python.exe"
set "ENTRYPOINT=%PROJECT_ROOT%pdf_to_jats\main.py"

if not exist "%PYTHON%" (
  set "PYTHON=%PROJECT_ROOT%p313\Scripts\python.exe"
  if not exist "%PYTHON%" (
    where python >nul 2>nul
    if not errorlevel 1 (
      set "PYTHON=python"
    ) else (
      where py >nul 2>nul
      if not errorlevel 1 (
        set "PYTHON=py -3"
      ) else (
        echo Python was not found. Install Python 3 and add it to PATH, or create C:\venvs\p313.
        exit /b 1
      )
    )
  )
)

if not exist "%ENTRYPOINT%" (
  echo Application entrypoint not found: "%ENTRYPOINT%"
  exit /b 1
)

%PYTHON% "%ENTRYPOINT%"
