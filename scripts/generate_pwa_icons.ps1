Add-Type -AssemblyName System.Drawing

$iconDir = "c:\Users\robym\Desktop\Documentos\Analise de dados\alertas-operacionais-op\alertas-operacionais-op\static\icons"
if (-not (Test-Path $iconDir)) {
    New-Item -ItemType Directory -Path $iconDir -Force | Out-Null
}

function Generate-PwaIcon {
    param(
        [int]$Size,
        [string]$Path,
        [bool]$IsMaskable = $false
    )

    $bmp = New-Object System.Drawing.Bitmap($Size, $Size)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality

    # Background Gradient (Deep midnight slate to electric dark cyan)
    $cTop = [System.Drawing.Color]::FromArgb(255, 11, 15, 25)
    $cBottom = [System.Drawing.Color]::FromArgb(255, 15, 23, 42)
    $rect = New-Object System.Drawing.Rectangle(0, 0, $Size, $Size)
    $bgBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush($rect, $cTop, $cBottom, [System.Drawing.Drawing2D.LinearGradientMode]::ForwardDiagonal)
    
    if ($IsMaskable) {
        $g.FillRectangle($bgBrush, $rect)
    } else {
        # Squircle background
        $path = New-Object System.Drawing.Drawing2D.GraphicsPath
        $radius = [int]($Size * 0.22)
        $d = $radius * 2
        $path.AddArc(0, 0, $d, $d, 180, 90)
        $path.AddArc($Size - $d, 0, $d, $d, 270, 90)
        $path.AddArc($Size - $d, $Size - $d, $d, $d, 0, 90)
        $path.AddArc(0, $Size - $d, $d, $d, 90, 90)
        $path.CloseFigure()
        $g.FillPath($bgBrush, $path)
        
        # Border glow
        $borderPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(140, 6, 182, 212), [float]($Size * 0.02))
        $g.DrawPath($borderPen, $path)
        $borderPen.Dispose()
        $path.Dispose()
    }

    # Center Emblem: Modern Shield with Radio waves & Lightning / Checkmark (Cyan / Amber glow)
    $center = $Size / 2
    $scale = $Size / 512.0
    
    # Outer circle ring
    $ringPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(80, 6, 182, 212), [float](6 * $scale))
    $ringSize = 340 * $scale
    $g.DrawEllipse($ringPen, [float]($center - $ringSize/2), [float]($center - $ringSize/2), [float]$ringSize, [float]$ringSize)
    $ringPen.Dispose()

    # Inner glowing polygon (Diamond / Shield)
    $points = @(
        New-Object System.Drawing.PointF($center, [float]($center - 130 * $scale)),
        New-Object System.Drawing.PointF([float]($center + 120 * $scale), [float]($center - 20 * $scale)),
        New-Object System.Drawing.PointF([float]($center + 80 * $scale), [float]($center + 130 * $scale)),
        New-Object System.Drawing.PointF($center, [float]($center + 160 * $scale)),
        New-Object System.Drawing.PointF([float]($center - 80 * $scale), [float]($center + 130 * $scale)),
        New-Object System.Drawing.PointF([float]($center - 120 * $scale), [float]($center - 20 * $scale))
    )
    $polyBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
        (New-Object System.Drawing.Rectangle(0, 0, $Size, $Size)),
        [System.Drawing.Color]::FromArgb(230, 6, 182, 212),
        [System.Drawing.Color]::FromArgb(230, 59, 130, 246),
        [System.Drawing.Drawing2D.LinearGradientMode]::Vertical
    )
    $g.FillPolygon($polyBrush, $points)

    # Core Icon: Letter "OP" or Checkmark + Pulse
    $fontFamily = New-Object System.Drawing.FontFamily("Arial")
    $fontStyle = [System.Drawing.FontStyle]::Bold
    $fontSize = [float](100 * $scale)
    $font = New-Object System.Drawing.Font($fontFamily, $fontSize, $fontStyle, [System.Drawing.GraphicsUnit]::Pixel)
    $strFormat = New-Object System.Drawing.StringFormat
    $strFormat.Alignment = [System.Drawing.StringAlignment]::Center
    $strFormat.LineAlignment = [System.Drawing.StringAlignment]::Center

    $textBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
    $textRect = New-Object System.Drawing.RectangleF(0, [float]($center - 60 * $scale), [float]$Size, [float](120 * $scale))
    $g.DrawString("OP", $font, $textBrush, $textRect, $strFormat)

    # Clean up
    $font.Dispose()
    $fontFamily.Dispose()
    $textBrush.Dispose()
    $polyBrush.Dispose()
    $bgBrush.Dispose()
    $g.Dispose()

    $bmp.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    Write-Output "Generated: $Path ($Size x $Size)"
}

Generate-PwaIcon -Size 192 -Path "$iconDir\icon-192.png"
Generate-PwaIcon -Size 512 -Path "$iconDir\icon-512.png"
Generate-PwaIcon -Size 512 -Path "$iconDir\icon-maskable.png" -IsMaskable $true
Generate-PwaIcon -Size 180 -Path "$iconDir\apple-touch-icon.png"
