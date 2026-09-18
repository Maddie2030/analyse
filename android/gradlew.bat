@echo off
setlocal
set "GRADLE_VERSION=9.6.0"
where gradle >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  gradle %*
  exit /b %ERRORLEVEL%
)
set "CACHE_DIR=%USERPROFILE%\.gradle\mreader-bootstrap\gradle-%GRADLE_VERSION%"
set "GRADLE_BIN=%CACHE_DIR%\gradle-%GRADLE_VERSION%\bin\gradle.bat"
if not exist "%GRADLE_BIN%" (
  if not exist "%CACHE_DIR%" mkdir "%CACHE_DIR%"
  echo Gradle not found; downloading Gradle %GRADLE_VERSION%...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $zip='%CACHE_DIR%\gradle.zip'; Invoke-WebRequest -Uri 'https://services.gradle.org/distributions/gradle-%GRADLE_VERSION%-bin.zip' -OutFile $zip; Expand-Archive -Path $zip -DestinationPath '%CACHE_DIR%' -Force; Remove-Item $zip"
  if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
)
call "%GRADLE_BIN%" %*
exit /b %ERRORLEVEL%
