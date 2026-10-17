# 停掉 Windows 侧 ui-tars MCP server 和本地 VLM
$killed = @()
Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object {
    $_.CommandLine -like '*ui-tars-mcp*'
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force
    $killed += 'mcp node pid ' + $_.ProcessId
}
Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force
    $killed += 'llama-server pid ' + $_.ProcessId
}
if ($killed.Count -eq 0) { Write-Output 'NO_PROCESS_FOUND' }
else { $killed | ForEach-Object { Write-Output $_ } }
