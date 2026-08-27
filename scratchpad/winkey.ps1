# Focus a window (by title) and send a real key press+release.
# SDL2 discards posted WM_KEYDOWN when the window has no keyboard focus, so PostMessage is not
# enough. Windows' foreground lock also blocks a bare SetForegroundWindow from a background
# process -- the AttachThreadInput dance is what makes it stick. Then keybd_event synthesises
# input at the driver level, which SDL sees exactly like a human keypress.
param([string]$Title = "FlipJump", [int]$Vk = 13, [int]$HoldMs = 120)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class K {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern IntPtr SetFocus(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr p);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
}
"@

function Focus-Window([IntPtr]$h) {
  $target = [K]::GetWindowThreadProcessId($h, [IntPtr]::Zero)
  $me = [K]::GetCurrentThreadId()
  [K]::AttachThreadInput($me, $target, $true) | Out-Null
  [K]::ShowWindow($h, 9) | Out-Null
  [K]::BringWindowToTop($h) | Out-Null
  [K]::SetForegroundWindow($h) | Out-Null
  [K]::SetFocus($h) | Out-Null
  [K]::AttachThreadInput($me, $target, $false) | Out-Null
  Start-Sleep -Milliseconds 250
  return ([K]::GetForegroundWindow() -eq $h)
}

$procs = Get-Process | Where-Object { $_.MainWindowTitle -like "*$Title*" -and $_.MainWindowHandle -ne 0 }
if (-not $procs) { Write-Output "NO WINDOW matching '$Title'"; exit 1 }
$h = $procs[0].MainWindowHandle
$got = Focus-Window $h
Write-Output ("focus: " + $got + "  window: '" + $procs[0].MainWindowTitle + "'")
if ($Vk -ge 0) {
  [K]::keybd_event([byte]$Vk, 0, 0, [UIntPtr]::Zero)          # down
  Start-Sleep -Milliseconds $HoldMs
  [K]::keybd_event([byte]$Vk, 0, 2, [UIntPtr]::Zero)          # up (KEYEVENTF_KEYUP)
  Write-Output ("sent vk=" + $Vk + " for " + $HoldMs + "ms")
}
