Option Explicit

Dim shell, fso, scriptPath, scriptDir, projectDir
Dim powerShellPath, powerShellEntryPath, runtimeDir, launcherDir, logPath
Dim action, noBrowser, command, processId, runId, launcherPythonPath

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
runId = CreateRunId()

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
    & " -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command " _
    & Quote(BuildPowerShellEntryCommand())

WriteLog "desktop_entry_vbs.started", "info", "Launching hidden PowerShell desktop entry.", "action=" & action & ";no_browser=" & CStr(noBrowser)

On Error Resume Next
processId = StartHiddenProcess(command, projectDir)
If Err.Number <> 0 Then
    WriteLog "desktop_entry_vbs.failed", "error", "Failed to launch hidden PowerShell desktop entry.", "error=" & Err.Description
    ShowFailure "Failed to launch Vibelution:" & vbCrLf & Err.Description & vbCrLf & vbCrLf & "Log: " & logPath
    WScript.Quit 1
End If
On Error GoTo 0

WriteLog "desktop_entry_vbs.launched", "info", "Hidden PowerShell desktop entry launched.", "action=" & action & ";process_id=" & CStr(processId) & ";launch_api=wmi_hidden_process"
ShowLaunchFeedback action
WScript.Quit 0

Function ResolveAction()
    Dim candidate, i, value, lowered
    candidate = "launcher"
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
        ElseIf Left(value, 1) <> "-" And candidate = "launcher" Then
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
        Case "launcher", "toggle", "start", "open", "stop", "close", "restart", "status"
            IsAllowedAction = True
        Case Else
            IsAllowedAction = False
    End Select
End Function

Sub SetLauncherEnvironment()
    Dim env, venvPython
    Set env = shell.Environment("PROCESS")
    env("VIBELUTION_DESKTOP_ENTRY_VBS_RUN_ID") = runId
    launcherPythonPath = ""
    venvPython = fso.BuildPath(projectDir, ".venv\Scripts\python.exe")

    If fso.FileExists(venvPython) Then
        launcherPythonPath = venvPython
        env("VIBELUTION_PYTHON_EXE") = venvPython
        WriteLog "desktop_entry_vbs.python_runtime.selected", "info", "Using Python runtime for desktop launch.", "path=" & venvPython
    End If
End Sub

Function BuildPowerShellEntryCommand()
    Dim text
    text = ""
    AppendPowerShellEnvAssignment text, "VIBELUTION_DESKTOP_ENTRY_VBS_RUN_ID", runId
    If Len(launcherPythonPath) > 0 Then
        AppendPowerShellEnvAssignment text, "VIBELUTION_PYTHON_EXE", launcherPythonPath
    End If
    AppendExistingPowerShellEnvAssignment text, "VIBELUTION_DESKTOP_ENTRY_START_MUTEX_NAME"
    AppendExistingPowerShellEnvAssignment text, "VIBELUTION_DESKTOP_ENTRY_ACTION_TIMEOUT_SECONDS"
    AppendExistingPowerShellEnvAssignment text, "VIBELUTION_DESKTOP_ENTRY_SUPPRESS_FEEDBACK"
    AppendExistingPowerShellEnvAssignment text, "VIBELUTION_DESKTOP_ENTRY_SHOW_FEEDBACK"
    text = text & "& " & PowerShellSingleQuoted(powerShellEntryPath) & " -Action " & PowerShellSingleQuoted(action)
    If noBrowser Then
        text = text & " -NoBrowser"
    End If
    BuildPowerShellEntryCommand = text
End Function

Sub AppendExistingPowerShellEnvAssignment(ByRef text, name)
    Dim value
    value = shell.Environment("PROCESS")(name)
    If Len(value) > 0 Then
        AppendPowerShellEnvAssignment text, name, value
    End If
End Sub

Sub AppendPowerShellEnvAssignment(ByRef text, name, value)
    text = text & "$env:" & name & " = " & PowerShellSingleQuoted(value) & "; "
End Sub

Function PowerShellSingleQuoted(value)
    PowerShellSingleQuoted = "'" & Replace(CStr(value), "'", "''") & "'"
End Function

Function CreateRunId()
    Dim value
    On Error Resume Next
    value = CreateObject("Scriptlet.TypeLib").Guid
    If Err.Number <> 0 Or Len(value) = 0 Then
        Err.Clear
        Randomize
        value = "{" & Year(Now) & Month(Now) & Day(Now) & Hour(Now) & Minute(Now) & Second(Now) & "-" & CStr(Int(Rnd() * 1000000)) & "}"
    End If
    On Error GoTo 0
    value = Replace(value, Chr(0), "")
    value = Replace(value, "{", "")
    value = Replace(value, "}", "")
    value = Replace(value, "-", "")
    CreateRunId = LCase(value)
End Function

Function ShouldSuppressFeedback()
    Dim value
    value = LCase(Trim(shell.Environment("PROCESS")("VIBELUTION_DESKTOP_ENTRY_SUPPRESS_FEEDBACK")))
    ShouldSuppressFeedback = (value = "1" Or value = "true" Or value = "yes" Or value = "on")
End Function

Function ShouldShowFeedback()
    Dim value
    value = LCase(Trim(shell.Environment("PROCESS")("VIBELUTION_DESKTOP_ENTRY_SHOW_FEEDBACK")))
    ShouldShowFeedback = (value = "1" Or value = "true" Or value = "yes" Or value = "on")
End Function

Function LaunchFeedbackMessage(value)
    Select Case LCase(Trim(value))
        Case "stop", "close"
            LaunchFeedbackMessage = "Vibelution is closing. This notice will close automatically."
        Case "restart"
            LaunchFeedbackMessage = "Vibelution is restarting. The app window will reopen shortly."
        Case "status"
            LaunchFeedbackMessage = "Vibelution status check has started. Details are written to the launcher log."
        Case Else
            LaunchFeedbackMessage = "Vibelution is opening. If it is already open, its window will be brought forward."
    End Select
End Function

Sub ShowLaunchFeedback(value)
    If ShouldSuppressFeedback() Then
        WriteLog "desktop_entry_vbs.feedback.suppressed", "info", "Desktop entry launch feedback was suppressed by environment.", "action=" & value
        Exit Sub
    End If

    If Not ShouldShowFeedback() Then
        WriteLog "desktop_entry_vbs.feedback.suppressed", "info", "Desktop entry launch feedback is quiet by default.", "action=" & value & ";reason=default_quiet"
        Exit Sub
    End If

    On Error Resume Next
    shell.Popup LaunchFeedbackMessage(value), 2, "Vibelution", vbInformation
    If Err.Number <> 0 Then
        WriteLog "desktop_entry_vbs.feedback.failed", "warning", "Failed to show desktop entry launch feedback.", "action=" & value & ";error=" & Err.Description
        Err.Clear
    Else
        WriteLog "desktop_entry_vbs.feedback.shown", "info", "Desktop entry launch feedback was shown.", "action=" & value & ";timeout_seconds=2"
    End If
    On Error GoTo 0
End Sub

Function StartHiddenProcess(commandLine, workingDirectory)
    Dim service, startup, processClass, returnCode, createdPid
    Set service = GetObject("winmgmts:{impersonationLevel=impersonate}!\\.\root\cimv2")
    Set startup = service.Get("Win32_ProcessStartup").SpawnInstance_
    startup.ShowWindow = 0
    ' CREATE_NO_WINDOW + CREATE_NEW_PROCESS_GROUP. DETACHED_PROCESS makes PowerShell start but skip the command body here.
    startup.CreateFlags = 134218240
    Set processClass = service.Get("Win32_Process")
    returnCode = processClass.Create(commandLine, workingDirectory, startup, createdPid)
    If returnCode <> 0 Then
        Err.Raise vbObjectError + 1701, "StartHiddenProcess", "Win32_Process.Create failed with code " & CStr(returnCode)
    End If
    StartHiddenProcess = CLng(createdPid)
End Function

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
    If Len(runId) > 0 Then
        If Len(details) > 0 Then
            details = details & ";run_id=" & runId
        Else
            details = "run_id=" & runId
        End If
    End If
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
