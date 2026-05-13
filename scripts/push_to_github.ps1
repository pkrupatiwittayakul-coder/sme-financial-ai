# ── scripts/push_to_github.ps1 ────────────────────────────────────────────────
# One-click cleanup + reorganise + commit + push for the SME Financial AI MVP.
#
# Run from PowerShell:
#   cd "C:\Users\Acer\OneDrive\Desktop\AI Financial Statement Generator\AI Financial Statement Generation"
# Provide your GitHub PAT via environment variable before running:
#   $env:GH_TOKEN = "ghp_xxx..."
#   .\scripts\push_to_github.ps1
#   .\scripts\push_to_github.ps1
#
# The script:
#   1. Reorganises the project tree (docs/, scripts/) idempotently
#   2. Deletes dead/superseded files
#   3. Refreshes .gitignore
#   4. Stages, commits and pushes the result to GitHub
# ──────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
$REPO_URL = $(if ($env:GH_TOKEN) { "https://pkrupatiwittayakul-coder:$($env:GH_TOKEN)@github.com/pkrupatiwittayakul-coder/sme-financial-ai.git" } else { "https://github.com/pkrupatiwittayakul-coder/sme-financial-ai.git" })

# Resolve project root = parent of this script's folder
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$ROOT       = Split-Path -Parent $SCRIPT_DIR
Set-Location $ROOT
Write-Host "Working in: $ROOT" -ForegroundColor Cyan

# ── 1. Ensure new folder layout ───────────────────────────────────────────────
$folders = @("docs", "scripts")
foreach ($d in $folders) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Path $d | Out-Null
        Write-Host "[mkdir] $d" -ForegroundColor Yellow
    }
}

# ── 2. Move kept files into their new homes (idempotent) ──────────────────────
function Move-IfExists($src, $dst) {
    if ((Test-Path $src) -and (-not (Test-Path $dst))) {
        Move-Item -Path $src -Destination $dst -Force
        Write-Host "[move] $src -> $dst" -ForegroundColor Yellow
    } elseif ((Test-Path $src) -and (Test-Path $dst)) {
        # destination already exists — overwrite the old root copy
        Remove-Item $src -Force
        Write-Host "[trim] $src (duplicate, kept $dst)" -ForegroundColor DarkGray
    }
}

Move-IfExists "SME_Financial_AI_MVP_v2_Report.pdf"  "docs\MVP_v2_Report.pdf"
Move-IfExists "ADR-001-architecture-hardening.md"   "docs\ADR-001-architecture-hardening.md"
Move-IfExists "design_prototype.html"                "docs\design_prototype.html"

# ── 3. Delete dead / superseded files ────────────────────────────────────────
$dead = @(
    # Legacy PDFs — superseded by docs/MVP_v2_Report.pdf
    "Expanded_SME_Financial_AI_Implementation_Report.pdf",
    "SME_Financial_AI_Implementation_Report.pdf",
    "SME_Financial_AI_MVP_Report.pdf",
    # Empty dev DB
    "sme_financial.db",
    "sme_financial.db-journal",
    # Legacy Streamlit frontend (replaced by backend/dashboard.html)
    "frontend\app.py",
    # Stale handoff doc (replaced by README.md + docs/)
    "HANDOFF.md",
    # Stale shell test (the new design API has no shell test yet)
    "test_api.sh",
    # Old root-level push script (replaced by scripts\push_to_github.ps1)
    "push_to_github.ps1",
    # Old build helper that lived in outputs (not part of the repo)
    "build_report.py",
    # Pycache leftovers
    "backend\__pycache__",
    "backend\api\__pycache__",
    "backend\models\__pycache__",
    "backend\services\__pycache__",
    # Stray dotfiles from sandbox testing
    "docs\.tmp"
)

foreach ($f in $dead) {
    if (Test-Path $f) {
        Remove-Item -Path $f -Recurse -Force
        Write-Host "[drop] $f" -ForegroundColor DarkRed
    }
}

# Drop empty frontend/ folder if app.py was its only resident
if ((Test-Path "frontend") -and (-not (Get-ChildItem "frontend" -Force))) {
    Remove-Item "frontend" -Recurse -Force
    Write-Host "[drop] frontend\ (empty)" -ForegroundColor DarkRed
}

# ── 4. Refresh .gitignore at the root ────────────────────────────────────────
$gitignore = @"
# Environment
.env
.env.local

# Python
__pycache__/
*.py[cod]
*.pyo
*.pyd
.Python
*.egg-info/
dist/
build/
.eggs/

# Virtual envs
venv/
.venv/
env/

# Database (runtime artefacts — never commit)
*.db
*.db-journal
*.db-wal
*.db-shm
*.sqlite
sme_financial.db*

# Uploads / generated reports
backend/storage/uploads/
backend/storage/reports/
sme_reports/
sme_uploads/

# Legacy (kept locally, not in repo)
Expanded_SME_Financial_AI_Implementation_Report.pdf
SME_Financial_AI_Implementation_Report.pdf
SME_Financial_AI_MVP_Report.pdf
frontend/app.py
HANDOFF.md
test_api.sh

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Logs
*.log
"@
Set-Content -Path ".gitignore" -Value $gitignore -Encoding UTF8
Write-Host "[ok] .gitignore refreshed" -ForegroundColor Green

# ── 5. Git init / remote ─────────────────────────────────────────────────────
if (-not (Test-Path ".git")) {
    Write-Host "[git] init" -ForegroundColor Yellow
    git init
    git branch -M main
} else {
    @(".git\config.lock", ".git\index.lock") | ForEach-Object {
        if (Test-Path $_) { Remove-Item $_ -Force; Write-Host "[git] released $_" }
    }
}
git config user.email "pkrupatiwittayakul@gmail.com"
git config user.name  "pkrupatiwittayakul-coder"

$remotes = git remote 2>$null
if ($remotes -contains "origin") {
    git remote set-url origin $REPO_URL
} else {
    git remote add origin $REPO_URL
}

# Untrack files that are now gitignored or have moved
git rm -r --cached --ignore-unmatch "frontend/app.py" 2>$null | Out-Null
git rm -r --cached --ignore-unmatch "HANDOFF.md" 2>$null | Out-Null
git rm -r --cached --ignore-unmatch "test_api.sh" 2>$null | Out-Null
git rm -r --cached --ignore-unmatch "ADR-001-architecture-hardening.md" 2>$null | Out-Null
git rm -r --cached --ignore-unmatch "design_prototype.html" 2>$null | Out-Null
git rm -r --cached --ignore-unmatch "SME_Financial_AI_MVP_Report.pdf" 2>$null | Out-Null
git rm -r --cached --ignore-unmatch "SME_Financial_AI_Implementation_Report.pdf" 2>$null | Out-Null
git rm -r --cached --ignore-unmatch "Expanded_SME_Financial_AI_Implementation_Report.pdf" 2>$null | Out-Null
git rm -r --cached --ignore-unmatch "push_to_github.ps1" 2>$null | Out-Null
git rm -r --cached --ignore-unmatch "sme_financial.db" 2>$null | Out-Null
git rm -r --cached --ignore-unmatch "sme_financial.db-journal" 2>$null | Out-Null

# ── 6. Stage everything ───────────────────────────────────────────────────────
Write-Host "[git] staging" -ForegroundColor Yellow
git add -A

$status = git status --short
if (-not $status) {
    Write-Host "[git] nothing to commit — repo already clean." -ForegroundColor Cyan
} else {
    Write-Host "[git] changes to commit:" -ForegroundColor Cyan
    Write-Host $status

    $msg = "chore: clean up legacy files + reorganise project (docs/, scripts/) + LLM two-sequence MVP v2"

    git commit -m $msg
    Write-Host "[git] committed" -ForegroundColor Green

    Write-Host "[git] pushing..." -ForegroundColor Yellow
    git push --set-upstream origin main --force-with-lease 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "Push successful:" -ForegroundColor Green
        Write-Host "  https://github.com/pkrupatiwittayakul-coder/sme-financial-ai" -ForegroundColor Cyan
        Write-Host "  Render will auto-deploy in ~2 min." -ForegroundColor Magenta
        Write-Host "  Live: https://sme-financial-ai.onrender.com" -ForegroundColor Cyan
    } else {
        Write-Host "Push failed — see output above." -ForegroundColor Red
    }
}

Write-Host "