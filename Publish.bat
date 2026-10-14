@echo off
rem Publish the portfolio: encrypt everything in private\projects and upload it to GitHub Pages.
rem Put files into private\projects\<project folder>\, then double-click this file.
cd /d "%~dp0"
echo Building the portfolio...
python tools\build.py || goto :error
git add -A || goto :error
git diff --cached --quiet && (echo Nothing changed, nothing to upload. & goto :done)
git commit -q -m "Update portfolio content" || goto :error
echo Uploading to GitHub...
git push -q origin main || goto :error
echo.
echo Done. The site updates in 1-2 minutes: https://patembedded.github.io/Portfolio/
goto :done
:error
echo.
echo Something went wrong; read the messages above.
:done
echo.
pause
