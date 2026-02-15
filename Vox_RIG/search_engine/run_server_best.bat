
@echo off
setlocal enabledelayedexpansion

REM VoxAI Search - Best preset server runner (Windows)
REM - Uses dim=1536 (matches typical OpenAI embeddings)
REM - Uses data directory ./data
REM - Refuses to start if existing vectors.bin was created with a different dim
REM - Set VOX_DIM or VOX_DATA_DIR to override

set "ADDR=:8080"
if not "%~1"=="" set "ADDR=%~1"

set "DATA_DIR=%CD%\data"
if not "%VOX_DATA_DIR%"=="" set "DATA_DIR=%VOX_DATA_DIR%"

set "DIM=1536"
if not "%VOX_DIM%"=="" set "DIM=%VOX_DIM%"

set "VEC_FILE=%DATA_DIR%\vectors.bin"

if not exist "%DATA_DIR%" (
  mkdir "%DATA_DIR%" >nul 2>nul
)

REM If vectors.bin exists, verify its dimension by reading one vector record.
REM File layout: [8-byte count][float32 values... contiguous vectors]
REM We don't rely on file size/count math (can be wrong if file was preallocated and not full).
if exist "%VEC_FILE%" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$p='%VEC_FILE%';" ^
    "$dim=%DIM%;" ^
    "$fs=[System.IO.File]::Open($p,[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,[System.IO.FileShare]::ReadWrite);" ^
    "try{" ^
    "  $br=New-Object System.IO.BinaryReader($fs);" ^
    "  $count=$br.ReadUInt64();" ^
    "  if($count -gt 0){" ^
    "    $size=(Get-Item $p).Length;" ^
    "    $payload=$size-8;" ^
    "    $bytesPerVec=[int64][Math]::Floor($payload / $count);" ^
    "    $inferred=[int][Math]::Floor($bytesPerVec/4);" ^
    "    if($inferred -ne $dim){" ^
    "      Write-Host 'ERROR: vectors.bin dimension mismatch.';" ^
    "      Write-Host ('  File appears to be dim=' + $inferred + ' (approx), but you are starting server with dim=' + $dim);" ^
    "      Write-Host '  Fix: delete data\\vectors.bin (and metadata.db) OR set VOX_DIM to match existing data.';" ^
    "      exit 2" ^
    "    }" ^
    "  }" ^
    "} finally { $fs.Close() }"
  if errorlevel 2 (
    exit /b 2
  )
)

echo Starting vox-vector-engine...
echo   addr     = %ADDR%
echo   data dir = %DATA_DIR%
echo   dim      = %DIM%
echo.

go run .\cmd\server -addr %ADDR% -data "%DATA_DIR%" -dim %DIM%
