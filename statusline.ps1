# Ponte entre a statusline do Claude Code e o statusline.py.
# Usado via: powershell -NoProfile -File C:/Users/<usuario>/.claude/usage-widget/statusline.ps1
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$json = [Console]::In.ReadToEnd()
$json | & "$PSScriptRoot\run-python.cmd" python "$PSScriptRoot\statusline.py"
exit $LASTEXITCODE
