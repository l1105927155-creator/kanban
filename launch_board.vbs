Option Explicit
' 个人任务看板 - 启动器
' 逻辑：服务启动时会把端口写入 port.txt；启动器直接读取该文件，无需扫描端口段。
'       未运行则用 pyw 无窗口启动 server.py，等端口文件出现且可用后打开应用窗口。

Dim fso, sh, appDir, portFile, baseUrl

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
portFile = fso.BuildPath(appDir, "port.txt")

baseUrl = ReadRunning(portFile)

If baseUrl = "" Then
  Dim serverPath, launched, n
  serverPath = fso.BuildPath(appDir, "server.py")
  If Not fso.FileExists(serverPath) Then
    MsgBox "未找到 server.py，请确认任务看板文件完整。", 16, "个人任务看板"
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

  ' 最多等待约 18 秒
  For n = 1 To 60
    WScript.Sleep 300
    baseUrl = ReadRunning(portFile)
    If baseUrl <> "" Then Exit For
  Next
End If

If baseUrl = "" Then
  MsgBox "任务看板启动失败：未能启动本地服务。" & vbCrLf & vbCrLf & _
         "请确认已安装 Python（命令行执行 py --version 有输出）。" & vbCrLf & _
         "也可以在命令行进入本文件夹运行 server.py 查看具体错误。", 16, "个人任务看板"
  WScript.Quit 1
End If

OpenApp baseUrl

' ---------- 函数 ----------

' 读取 port.txt 并确认该端口的看板可用；不可用则返回空串
Function ReadRunning(path)
  Dim f, txt, url
  ReadRunning = ""
  If Not fso.FileExists(path) Then Exit Function
  On Error Resume Next
  Set f = fso.OpenTextFile(path, 1)
  txt = Trim(f.ReadAll)
  f.Close
  On Error GoTo 0
  If Not IsNumeric(txt) Then Exit Function
  url = "http://127.0.0.1:" & CLng(txt)
  If IsBoardUp(url) Then ReadRunning = url & "/"
End Function

Function IsBoardUp(base)
  Dim http
  IsBoardUp = False
  On Error Resume Next
  Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
  If Err.Number = 0 Then
    http.setTimeouts 200, 200, 800, 800
    ' 先查接口确认是看板服务，再查根路径确认页面真的发得出来。
    ' 只看 /api/health 会把"半死"实例误判为已就绪（网页无法正常运作）。
    http.open "GET", base & "/api/health", False
    http.send
    If Err.Number = 0 Then
      If http.status = 200 Then
        If InStr(http.responseText, "task-board") > 0 Then
          http.open "GET", base & "/", False
          http.send
          If Err.Number = 0 Then
            If http.status = 200 Then
              If Len(http.responseText) > 0 Then IsBoardUp = True
            End If
          End If
        End If
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
