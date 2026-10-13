Option Explicit
' 个人开发任务看板 - 启动器
' 逻辑：先探测本地服务是否已在运行（端口 8737-8746），
'       未运行则用 pyw 无窗口启动 server.py，等待就绪后打开应用窗口。

Dim fso, sh, appDir, ports, baseUrl

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)

ports = Array(8737, 8738, 8739, 8740, 8741, 8742, 8743, 8744, 8745, 8746)
baseUrl = FindRunning(ports)

If baseUrl = "" Then
  Dim serverPath, launched, n
  serverPath = fso.BuildPath(appDir, "server.py")
  If Not fso.FileExists(serverPath) Then
    MsgBox "未找到 server.py，请确认任务看板文件完整。", 16, "个人开发任务看板"
    WScript.Quit 1
  End If

  ' 优先 pyw（无控制台窗口），失败则尝试 pythonw
  On Error Resume Next
  sh.Run "pyw.exe """ & serverPath & """", 0, False
  launched = (Err.Number = 0)
  Err.Clear
  If Not launched Then
    sh.Run "pythonw.exe """ & serverPath & """", 0, False
    launched = (Err.Number = 0)
    Err.Clear
  End If
  On Error GoTo 0

  ' 最多等待 20 秒
  For n = 1 To 40
    WScript.Sleep 500
    baseUrl = FindRunning(ports)
    If baseUrl <> "" Then Exit For
  Next
End If

If baseUrl = "" Then
  MsgBox "任务看板启动失败：未能启动本地服务。" & vbCrLf & vbCrLf & _
         "请确认已安装 Python（命令行执行 py --version 有输出）。" & vbCrLf & _
         "也可以在命令行进入本文件夹运行 server.py 查看具体错误。", 16, "个人开发任务看板"
  WScript.Quit 1
End If

OpenApp baseUrl

' ---------- 函数 ----------

Function FindRunning(portList)
  Dim j, url
  FindRunning = ""
  For j = 0 To UBound(portList)
    url = "http://127.0.0.1:" & portList(j)
    If IsBoardUp(url) Then
      FindRunning = url & "/"
      Exit Function
    End If
  Next
End Function

Function IsBoardUp(base)
  Dim http
  IsBoardUp = False
  On Error Resume Next
  Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
  If Err.Number = 0 Then
    http.setTimeouts 400, 400, 800, 800
    http.open "GET", base & "/api/health", False
    http.send
    If Err.Number = 0 Then
      If http.status = 200 Then
        If InStr(http.responseText, "task-board") > 0 Then IsBoardUp = True
      End If
    End If
  End If
  Err.Clear
  On Error GoTo 0
End Function

Sub OpenApp(url)
  Dim chrome, edge
  chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
  edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
  If fso.FileExists(chrome) Then
    sh.Run """" & chrome & """ --app=" & url & " --window-size=1480,920", 1, False
  ElseIf fso.FileExists(edge) Then
    sh.Run """" & edge & """ --app=" & url & " --window-size=1480,920", 1, False
  Else
    sh.Run url, 1, False
  End If
End Sub
