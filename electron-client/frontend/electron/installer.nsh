!define BT_NMS_WATCHDOG_TASK "BeiTongNmsClientWatchdog"
!define BT_NMS_LOGIN_ITEM "BeiTongNmsClient"
!define BT_NMS_BACKGROUND_ARGUMENT "--watchdog-launch"
!define BT_NMS_INSTALL_MARKER ".bt-nms-watchdog-installed"

!macro customInstall
  FileOpen $0 "$INSTDIR\${BT_NMS_INSTALL_MARKER}" w
  FileWrite $0 "installed"
  FileClose $0
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "${BT_NMS_LOGIN_ITEM}" '"$INSTDIR\${APP_EXECUTABLE_FILENAME}" ${BT_NMS_BACKGROUND_ARGUMENT}'
  nsExec::ExecToLog '"$SYSDIR\schtasks.exe" /Create /F /TN "${BT_NMS_WATCHDOG_TASK}" /SC MINUTE /MO 1 /RL LIMITED /TR "$\"$INSTDIR\${APP_EXECUTABLE_FILENAME}$\" ${BT_NMS_BACKGROUND_ARGUMENT}"'
!macroend

!macro customUnInstall
  nsExec::ExecToLog '"$SYSDIR\schtasks.exe" /Delete /F /TN "${BT_NMS_WATCHDOG_TASK}"'
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "${BT_NMS_LOGIN_ITEM}"
  Delete "$INSTDIR\${BT_NMS_INSTALL_MARKER}"
!macroend
