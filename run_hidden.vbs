' run_hidden.vbs - launch the tray app with no console window.
' Double-click it, or put a shortcut to it in shell:startup for autostart.

Option Explicit
Dim fso, sh, base, pyw, script

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

base   = fso.GetParentFolderName(WScript.ScriptFullName)
pyw    = base & "\.venv\Scripts\pythonw.exe"
script = base & "\tray_app.py"

If Not fso.FileExists(pyw) Then
    MsgBox "pythonw.exe not found at:" & vbCrLf & pyw & vbCrLf & vbCrLf & _
           "Create the venv first:  python -m venv .venv", 16, "ancs_notifier"
    WScript.Quit 1
End If

sh.CurrentDirectory = base
sh.Run """" & pyw & """ """ & script & """", 0, False
