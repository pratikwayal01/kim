# Sound Configuration

kim can play sounds with notifications. You can use the system default sound or specify a custom sound file.

## Sound Settings

In `~/.kim/config.json`:

```json
{
  "sound": true,
  "sound_file": null
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `sound` | boolean | `true` | Enable/disable sound globally |
| `sound_file` | string/null | `null` | Path to custom sound file |

## Supported Formats

| Platform | Supported Formats |
|---|---|
| Linux | wav, ogg, flac, mp3 (via paplay/aplay/ffplay/mpv) |
| macOS | wav, mp3, aiff, m4a, aac (via afplay) |
| Windows | wav only (via winsound/PowerShell), other formats via Windows Media Player |

## Managing Sound via CLI

### Show Current Configuration

```bash
kim sound
```

### Set Custom Sound File

```bash
kim sound --set /path/to/sound.wav
```

The file is validated for existence and supported extension.

### Revert to System Default

```bash
kim sound --clear
```

### Test Current Sound

```bash
kim sound --test
```

Plays the configured sound (custom or default).

### Enable/Disable Sound

```bash
kim sound --enable
kim sound --disable
```

## Platform-Specific Notes

### Linux

Requires one of the following audio players:
- `paplay` (PulseAudio)
- `aplay` (ALSA)
- `ffplay` (FFmpeg)
- `mpv`
- `cvlc` (VLC)

Default system sound: `canberra-gtk-play --id=bell` or `/usr/share/sounds/freedesktop/stereo/bell.oga`.

### macOS

Uses `afplay` (built-in). Default system sound: Glass.

### Windows

- **wav files**: Uses `winsound` module (stdlib) or PowerShell `SoundPlayer`
- **Other formats**: Uses Windows Media Player via PowerShell
- Default system sound: Windows default beep

## Custom Sound Examples

### Linux

```bash
kim sound --set /usr/share/sounds/freedesktop/stereo/complete.oga
```

### macOS

```bash
kim sound --set ~/Music/sounds/glass.aiff
```

### Windows

```bash
kim sound --set "C:\Windows\Media\Windows Notify System Generic.wav"
```

## Troubleshooting

### Sound Not Playing

1. Check if sound is enabled: `kim sound`
2. Verify sound file exists and is readable
3. Test with `kim sound --test`
4. Check logs: `kim logs`

### Permission Issues

Ensure the sound file is readable by the user running kim.

### Missing Audio Players (Linux)

Install one of the supported players:
```bash
# Debian/Ubuntu
sudo apt install pulseaudio-utils alsa-utils ffmpeg mpv vlc

# Arch
sudo pacman -P pulseaudio alsa-utils ffmpeg mpv vlc
```