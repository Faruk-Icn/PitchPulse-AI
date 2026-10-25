param(
    [string]$Output = 'media/pitchpulse-pitch.mp4'
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$source = Join-Path $repository 'media/production'
$slideFile = (Resolve-Path (Join-Path $source 'slides.html')).Path.Replace('\', '/')
$narration = Get-Content -LiteralPath (Join-Path $source 'narration.json') -Raw | ConvertFrom-Json
$build = Join-Path $env:TEMP ('pitchpulse-video-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $build | Out-Null
$edge = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
if (-not (Test-Path $edge)) { $edge = (Get-Command msedge -ErrorAction Stop).Source }
$ffmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source
$ffprobe = (Get-Command ffprobe -ErrorAction Stop).Source
$synthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synthesizer.Rate = 2
$segments = @()

for ($index = 0; $index -lt $narration.Count; $index++) {
    $number = $index + 1
    $image = Join-Path $build ('slide-{0:D2}.png' -f $number)
    $audio = Join-Path $build ('voice-{0:D2}.wav' -f $number)
    $segment = Join-Path $build ('segment-{0:D2}.mp4' -f $number)
    $profile = Join-Path $build ('edge-profile-{0:D2}' -f $number)
    $uri = 'file:///' + $slideFile + '?slide=' + $number
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $edge --headless=new --disable-gpu --no-first-run --hide-scrollbars --window-size=1600,900 --virtual-time-budget=2500 --user-data-dir=$profile --screenshot=$image $uri 2>$null | Out-Null
    $ErrorActionPreference = $previousPreference
    for ($attempt = 0; $attempt -lt 50 -and -not (Test-Path $image); $attempt++) {
        Start-Sleep -Milliseconds 200
    }
    if (-not (Test-Path $image)) { throw "Slide $number could not be rendered" }

    $synthesizer.SetOutputToWaveFile($audio)
    $synthesizer.Speak([string]$narration[$index])
    $synthesizer.SetOutputToNull()
    $voiceDuration = [double](& $ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $audio)
    $duration = $voiceDuration + 1.6
    $fadeOut = [Math]::Max(0, $duration - 0.3)
    $filter = "[0:v]scale=1280:720,format=yuv420p,fade=t=in:st=0:d=0.25,fade=t=out:st=$fadeOut`:d=0.3[v];[1:a]apad=pad_dur=1.6[a]"
    & $ffmpeg -hide_banner -loglevel error -y -loop 1 -framerate 30 -i $image -i $audio -filter_complex $filter -map '[v]' -map '[a]' -t $duration -c:v libx264 -preset medium -crf 22 -r 30 -c:a aac -b:a 128k -movflags +faststart $segment
    if ($LASTEXITCODE -ne 0) { throw "Video segment $number failed" }
    $segments += $segment
}
$synthesizer.Dispose()
$list = Join-Path $build 'segments.txt'
$segments | ForEach-Object { "file '$($_.Replace('\', '/'))'" } | Set-Content -LiteralPath $list -Encoding ASCII
$destination = Join-Path $repository $Output
& $ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i $list -c copy -movflags +faststart $destination
if ($LASTEXITCODE -ne 0) { throw 'Final video assembly failed' }
$finalDuration = & $ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $destination
Write-Output "Video: $destination"
Write-Output "Duration: $finalDuration seconds"
