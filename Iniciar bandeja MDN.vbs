' Mi Dia Nutricional — arranque silencioso del icono de bandeja.
' Lanza bandeja_mdn.py con pythonw (sin consola) y con la ventana oculta (el 0 del Run).
' Este archivo es el que va en la carpeta de Inicio de Windows.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
carpeta = fso.GetParentFolderName(WScript.ScriptFullName)

pyw = "C:\Python314\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = "pythonw.exe"

sh.Run """" & pyw & """ """ & carpeta & "\bandeja_mdn.py""", 0, False
