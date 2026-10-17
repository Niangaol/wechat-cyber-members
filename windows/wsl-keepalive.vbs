' WSL 常驻保活：始终维持一个 wsl.exe 客户端连接，避免 WSL2 在空闲 60s 后关闭虚拟机。
' 由「登录时」计划任务 WeChatBotKeepAlive 拉起，静默运行，无窗口。
' 卸载：schtasks /delete /tn WeChatBotKeepAlive /f  然后结束 wscript.exe 进程即可。
Option Explicit
Dim sh, distro, user
Set sh = CreateObject("WScript.Shell")
distro = "Ubuntu-24.04"
user = "niangao"
Do
    ' sleep 秒数用一个很大但安全的值；进程退出（如 WSL 重启）后循环重连
    On Error Resume Next
    sh.Run "wsl.exe -d " & distro & " -u " & user & " -e sleep 2147483", 0, True
    On Error GoTo 0
    WScript.Sleep 5000
Loop
