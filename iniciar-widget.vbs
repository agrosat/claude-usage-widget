' Inicia o widget de uso do Claude sem abrir janela de console.
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
CreateObject("WScript.Shell").Run """" & base & "\run-python.cmd"" pythonw """ & base & "\widget.pyw""", 0, False
