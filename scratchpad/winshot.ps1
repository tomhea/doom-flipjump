# Capture a top-level window (matched by title substring) to a PNG.
# Uses PrintWindow(PW_RENDERFULLCONTENT) so the window's OWN content is grabbed even when it is
# occluded or not focused -- CopyFromScreen grabs whatever pixels are on the desktop at those
# coordinates, which on a background window is the wallpaper.
param([string]$Title = "FlipJump", [string]$Out = "shot.png", [switch]$Focus)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
}
"@

$procs = Get-Process | Where-Object { $_.MainWindowTitle -like "*$Title*" -and $_.MainWindowHandle -ne 0 }
if (-not $procs) { Write-Output "NO WINDOW matching '$Title'"; exit 1 }
$h = $procs[0].MainWindowHandle
Write-Output ("window: '" + $procs[0].MainWindowTitle + "' (pid " + $procs[0].Id + ")")
if ($Focus) { [Win]::ShowWindow($h, 9) | Out-Null; [Win]::SetForegroundWindow($h) | Out-Null; Start-Sleep -Milliseconds 400 }

$r = New-Object Win+RECT
[Win]::GetClientRect($h, [ref]$r) | Out-Null
$w = $r.R - $r.L; $ht = $r.B - $r.T
if ($w -le 0 -or $ht -le 0) { Write-Output "ZERO-SIZE client area"; exit 1 }

Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap($w, $ht)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$dc = $g.GetHdc()
$ok = [Win]::PrintWindow($h, $dc, 2)      # 2 = PW_RENDERFULLCONTENT
$g.ReleaseHdc($dc)
$g.Dispose()
if (-not $ok) { Write-Output "PrintWindow FAILED" }
try {
  $fs = [System.IO.File]::Create($Out)
  $bmp.Save($fs, [System.Drawing.Imaging.ImageFormat]::Png)
  $fs.Close()
  Write-Output ("captured " + $w + "x" + $ht + " -> " + $Out)
} catch { Write-Output ("SAVE FAILED: " + $_.Exception.Message) }
$bmp.Dispose()
