# Cho batch retry chay xong -> sleep may tinh
$log = "D:\VTS\TestAgent\artifacts\library\_batch_retry_20261006.log"
$watchLog = "D:\VTS\TestAgent\artifacts\library\_sleep_watcher.log"
"[watcher] bat dau cho $(Get-Date -Format 'HH:mm:ss')" | Out-File $watchLog -Encoding UTF8

$deadline = (Get-Date).AddHours(2)
while ((Get-Date) -lt $deadline) {
  $content = Get-Content $log -Encoding UTF8 -ErrorAction SilentlyContinue | Out-String
  if ($content -match "TONG KET") { break }
  Start-Sleep 60
}
"[watcher] batch xong hoac timeout luc $(Get-Date -Format 'HH:mm:ss')" | Out-File $watchLog -Append -Encoding UTF8
Start-Sleep 15
"[watcher] sleep may tinh" | Out-File $watchLog -Append -Encoding UTF8
rundll32.exe powrprof.dll,SetSuspendState 0,1,0
