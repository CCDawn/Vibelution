Option Explicit

Dim shell, fso, scriptPath, scriptDir, projectDir
Dim powerShellPath, powerShellEntryPath, runtimeDir, launcherDir, logPath
Dim action, noBrowser, command, exitCode

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptPath = WScript.ScriptFullName
scriptDir = fso.GetParentFolderName(scriptPath)
projectDir = fso.GetParentFolderName(scriptDir)
powerShellEntryPath = fso.BuildPath(scriptDir, "vibelution_desktop_entry.ps1")
runtimeDir = fso.BuildPath(projectDir, ".runtime")
launcherDir = fso.BuildPath(runtimeDir, "launcher")
logPath = fso.BuildPath(launcherDir, "desktop-entry-vbs.log")
powerShellPath = shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"

action = ResolveAction()
noBrowser = ResolveNoBrowser()

On Error Resume Next
EnsureFolder launcherDir
If Err.Number <> 0 Then
    ShowFailure "Failed to create launcher log directory: " & Err.Description
    WScript.Quit 1
End If
On Error GoTo 0

If Not fso.FileExists(powerShellEntryPath) Then
    WriteLog "desktop_entry_vbs.failed", "error", "PowerShell desktop entry script not found.", "path=" & powerShellEntryPath
    ShowFailure "Desktop entry script not found:" & vbCrLf & powerShellEntryPath
    WScript.Quit 1
End If

If Not fso.FileExists(powerShellPath) Then
    WriteLog "desktop_entry_vbs.failed", "error", "Windows PowerShell executable not found.", "path=" & powerShellPath
    ShowFailure "Windows PowerShell was not found:" & vbCrLf & powerShellPath
    WScript.Quit 1
End If

If Not IsAllowedAction(action) Then
    WriteLog "desktop_entry_vbs.failed", "error", "Unsupported launcher action.", "action=" & action
    ShowFailure "Unsupported Vibelution action: " & action
    WScript.Quit 1
End If

SetLauncherEnvironment

command = Quote(powerShellPath) _
    & " -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " _
    & Quote(powerShellEntryPath) _
    & " -Action " & Quote(action)
If noBrowser Then
    command = command & " -NoBrowser"
End If

WriteLog "desktop_entry_vbs.started", "info", "Launching hidden PowerShell desktop entry.", "action=" & action & ";no_browser=" & CStr(noBrowser)

On Error Resume Next
exitCode = shell.Run(command, 0, False)
If Err.Number <> 0 Then
    WriteLog "desktop_entry_vbs.failed", "error", "Failed to launch hidden PowerShell desktop entry.", "error=" & Err.Description
    ShowFailure "Failed to launch Vibelution:" & vbCrLf & Err.Description & vbCrLf & vbCrLf & "Log: " & logPath
    WScript.Quit 1
End If
On Error GoTo 0

WriteLog "desktop_entry_vbs.launched", "info", "Hidden PowerShell desktop entry launched.", "action=" & action & ";shell_run_code=" & CStr(exitCode)
WScript.Quit 0

Function ResolveAction()
    Dim candidate, i, value, lowered
    candidate = "start"
    For i = 0 To WScript.Arguments.Count - 1
        value = Trim(WScript.Arguments(i))
        lowered = LCase(value)
        If lowered = "-action" Or lowered = "--action" Then
            If i + 1 < WScript.Arguments.Count Then
                candidate = LCase(Trim(WScript.Arguments(i + 1)))
                Exit For
            End If
        ElseIf Left(lowered, 8) = "-action:" Then
            candidate = LCase(Trim(Mid(value, 9)))
            Exit For
        ElseIf Left(lowered, 8) = "-action=" Then
            candidate = LCase(Trim(Mid(value, 9)))
            Exit For
        ElseIf Left(lowered, 9) = "--action:" Then
            candidate = LCase(Trim(Mid(value, 10)))
            Exit For
        ElseIf Left(lowered, 9) = "--action=" Then
            candidate = LCase(Trim(Mid(value, 10)))
            Exit For
        ElseIf Left(value, 1) <> "-" And candidate = "start" Then
            candidate = LCase(value)
        End If
    Next
    ResolveAction = candidate
End Function

Function ResolveNoBrowser()
    Dim i, value
    ResolveNoBrowser = False
    For i = 0 To WScript.Arguments.Count - 1
        value = LCase(Trim(WScript.Arguments(i)))
        If value = "--no-browser" Or value = "-nobrowser" Or value = "-no-browser" Then
            ResolveNoBrowser = True
            Exit Function
        End If
    Next
End Function

Function IsAllowedAction(value)
    Select Case LCase(Trim(value))
        Case "toggle", "start", "open", "stop", "close", "restart", "status"
            IsAllowedAction = True
        Case Else
            IsAllowedAction = False
    End Select
End Function

Sub SetLauncherEnvironment()
    Dim env, venvPython
    Set env = shell.Environment("PROCESS")
    venvPython = fso.BuildPath(projectDir, ".venv\Scripts\python.exe")
    If fso.FileExists(venvPython) Then
        env("VIBELUTION_PYTHON_EXE") = venvPython
    End If
End Sub

Sub EnsureFolder(path)
    Dim parent
    If fso.FolderExists(path) Then
        Exit Sub
    End If
    parent = fso.GetParentFolderName(path)
    If Len(parent) > 0 Then
        If Not fso.FolderExists(parent) Then
            EnsureFolder parent
        End If
    End If
    fso.CreateFolder path
End Sub

Sub WriteLog(eventName, level, message, details)
    Dim stream, line
    On Error Resume Next
    EnsureFolder launcherDir
    line = "{""ts"":""" & JsonEscape(NowIso()) & """,""level"":""" & JsonEscape(level) & """,""event"":""" & JsonEscape(eventName) & """,""message"":""" & JsonEscape(message) & """,""details"":""" & JsonEscape(details) & """}"
    Set stream = fso.OpenTextFile(logPath, 8, True)
    stream.WriteLine line
    stream.Close
    On Error GoTo 0
End Sub

Function NowIso()
    Dim current
    current = Now
    NowIso = Year(current) & "-" & Pad2(Month(current)) & "-" & Pad2(Day(current)) _
        & "T" & Pad2(Hour(current)) & ":" & Pad2(Minute(current)) & ":" & Pad2(Second(current))
End Function

Function Pad2(value)
    If CInt(value) < 10 Then
        Pad2 = "0" & CStr(value)
    Else
        Pad2 = CStr(value)
    End If
End Function

Function JsonEscape(value)
    Dim text
    text = CStr(value)
    text = Replace(text, "\", "\\")
    text = Replace(text, """", "\""")
    text = Replace(text, vbCr, "\r")
    text = Replace(text, vbLf, "\n")
    JsonEscape = text
End Function

Function Quote(value)
    Quote = """" & Replace(CStr(value), """", "\""") & """"
End Function

Sub ShowFailure(message)
    MsgBox message, vbCritical, "Vibelution Launcher"
End Sub
