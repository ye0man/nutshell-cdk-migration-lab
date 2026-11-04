param(
    [Parameter(Mandatory = $true)][ValidateSet('start-nutshell', 'start-cdk', 'stop', 'wait')]
    [string]$Action,
    [string]$RunDir,
    [string]$Exe,
    [int]$Port = 0,
    [string]$Mnemonic = '',
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'

function Start-Detached([string]$CommandLine) {
    $result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $CommandLine
    }
    if ($result.ReturnValue -ne 0) {
        throw "Win32_Process.Create failed with $($result.ReturnValue)"
    }
    return [int]$result.ProcessId
}

function Wait-Http([string]$Url, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return $true }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

switch ($Action) {
    'start-nutshell' {
        if (-not (Test-Path -LiteralPath $RunDir)) { throw "run dir not found: $RunDir" }
        $wrapper = Join-Path $RunDir 'start-mint.cmd'
        $lines = @(
            '@echo off',
            "cd /d `"$RunDir`"",
            "`"$Exe`" > `"$RunDir\mint.out.log`" 2> `"$RunDir\mint.err.log`""
        )
        Set-Content -LiteralPath $wrapper -Value $lines -Encoding ascii
        $launcherPid = Start-Detached "cmd.exe /c `"$wrapper`""
        Set-Content -LiteralPath (Join-Path $RunDir 'launcher.pid') -Value $launcherPid
        Write-Output "launcher=$launcherPid"
    }
    'start-cdk' {
        if (-not (Test-Path -LiteralPath $RunDir)) { throw "run dir not found: $RunDir" }
        $wrapper = Join-Path $RunDir 'start-mint.cmd'
        $lines = @(
            '@echo off',
            "cd /d `"$RunDir`"",
            "set CDK_MINTD_MNEMONIC=$Mnemonic",
            "`"$Exe`" --work-dir `"$RunDir`" > `"$RunDir\mint.out.log`" 2> `"$RunDir\mint.err.log`""
        )
        Set-Content -LiteralPath $wrapper -Value $lines -Encoding ascii
        $launcherPid = Start-Detached "cmd.exe /c `"$wrapper`""
        Set-Content -LiteralPath (Join-Path $RunDir 'launcher.pid') -Value $launcherPid
        Write-Output "launcher=$launcherPid"
    }
    'stop' {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        foreach ($connection in $connections) {
            try { Stop-Process -Id $connection.OwningProcess -Force -ErrorAction Stop } catch {}
        }
        Write-Output "stopped port $Port"
    }
    'wait' {
        $url = "http://127.0.0.1:$Port/v1/info"
        if (Wait-Http $url $TimeoutSeconds) {
            Write-Output 'ready'
        } else {
            Write-Output 'timeout'
            exit 1
        }
    }
}
