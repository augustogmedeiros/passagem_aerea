# Cria uma tarefa no Agendador do Windows que roda o bot 3x por dia (8h, 14h, 20h).
# Rode uma vez:  powershell -ExecutionPolicy Bypass -File agendar.ps1
# Para remover:  Unregister-ScheduledTask -TaskName "BotPassagens" -Confirm:$false

$pasta  = $PSScriptRoot
$python = Join-Path $pasta ".venv\Scripts\pythonw.exe"   # pythonw = sem janela piscando
$script = Join-Path $pasta "buscar_passagens.py"

$acao = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $pasta
$gatilhos = @("08:00", "14:00", "20:00") | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
# StartWhenAvailable: se o PC estava desligado no horário, roda assim que ligar
$opcoes = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
          -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName "BotPassagens" -Action $acao -Trigger $gatilhos -Settings $opcoes -Force | Out-Null
Write-Host "Tarefa 'BotPassagens' criada. Para testar agora: Start-ScheduledTask -TaskName BotPassagens"
