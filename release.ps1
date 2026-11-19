param([string]$Message)
$ErrorActionPreference = 'Stop'
$Repo = 'cplusruss/rcalc'
$Visibility = 'public'
$VersionFile = 'rcalc.py'
# group 2 is the x.y.z version
$VersionRegex = '^(\s*(?:__version__|VERSION)\s*=\s*.)(\d+\.\d+\.\d+)'
$Workflow = 'release.yml'
Set-Location $PSScriptRoot
$py = if ($env:PY) { $env:PY } else { 'C:\Python\313\python.exe' }

function Run($exe) {
    & $exe @args
    if ($LASTEXITCODE -ne 0) { throw "$exe $args failed ($LASTEXITCODE)" }
}

# stderr captured as text: under 'Stop', Windows PowerShell 5.1 turns a native stderr line into an exception
function Capture($exe) {
    $ErrorActionPreference = 'Continue'
    $out = & $exe @args 2>&1 | ForEach-Object { "$_" }
    [pscustomobject]@{ Code = $LASTEXITCODE; Text = ($out -join "`n") }
}

function Parse($v) {
    if ($v -notmatch '^v?(\d+)\.(\d+)\.(\d+)$') { throw "bad version '$v'" }
    [version]"$($Matches[1]).$($Matches[2]).$($Matches[3])"
}

# symbolic-ref also names the branch of a fresh repo with no commits yet
$r = Capture git symbolic-ref --short HEAD
if ($r.Code -ne 0) { throw 'detached HEAD: check out a branch first' }
$branch = $r.Text.Trim()

# nothing identifying or secret in the files or the unpushed history
Run $py .github\scan.py --repo $Repo --history

Get-ChildItem . -Filter *.py | ForEach-Object { Run $py -m py_compile $_.FullName }

$path = (Resolve-Path $VersionFile).Path
$text = [IO.File]::ReadAllText($path)
$m = [regex]::Match($text, $VersionRegex, 'Multiline')
if (-not $m.Success) { throw "version not found in $VersionFile" }
$version = Parse $m.Groups[2].Value

$r = Capture gh repo view $Repo --json name
if ($r.Code -eq 0) {
    $exists = $true
} elseif ($r.Text -match 'Could not resolve to a Repository') {
    $exists = $false
} else {
    throw "gh repo view failed: $($r.Text)"
}

$latest = [version]'0.0.0'
if ($exists) {
    $r = Capture gh release view --repo $Repo --json tagName --jq .tagName
    if ($r.Code -eq 0) {
        $latest = Parse $r.Text.Trim()
    } elseif ($r.Text -notmatch 'release not found') {
        throw "gh release view failed: $($r.Text)"
    }
}

if ($version -le $latest) {
    $version = [version]"$($latest.Major).$($latest.Minor).$($latest.Build + 1)"
    $g = $m.Groups[2]
    $text = $text.Substring(0, $g.Index) + "$version" + $text.Substring($g.Index + $g.Length)
    [IO.File]::WriteAllText($path, $text)
    Write-Host "version bumped to $version (latest release v$latest)"
}

Run git add -A
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    if (-not $Message) { $Message = "Release v$version" }
    Run git commit -m $Message
}

if (-not $exists) {
    Run gh repo create $Repo "--$Visibility" --source . --remote origin
} elseif ((Capture git remote get-url origin).Code -ne 0) {
    Run git remote add origin "https://github.com/$Repo.git"
}
Run git push -u origin $branch
$sha = (git rev-parse HEAD).Trim()

function Runs { gh run list --repo $Repo --workflow $Workflow --limit 20 --json databaseId,headSha | ConvertFrom-Json }

# a freshly pushed workflow can take a few seconds to register
for ($i = 0; ; $i++) {
    $r = Capture gh workflow view $Workflow --repo $Repo
    if ($r.Code -eq 0) { break }
    if ($i -ge 15) { throw "workflow $Workflow not found: $($r.Text)" }
    Start-Sleep -Seconds 2
}
$before = @(Runs | ForEach-Object { $_.databaseId })
Run gh workflow run $Workflow --repo $Repo --ref $branch -f "version=$version"
$id = $null
for ($i = 0; $i -lt 30 -and -not $id; $i++) {
    Start-Sleep -Seconds 2
    $id = (Runs | Where-Object { $_.headSha -eq $sha -and $before -notcontains $_.databaseId } | Select-Object -First 1).databaseId
}
if (-not $id) { throw 'release workflow run did not appear' }
Run gh run watch $id --repo $Repo --exit-status

$rel = gh release view "v$version" --repo $Repo --json url,assets | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "release v$version not found after the run" }
Write-Host $rel.url
$rel.assets | ForEach-Object { Write-Host ("{0}  {1:N1} MB" -f $_.name, ($_.size / 1MB)) }
