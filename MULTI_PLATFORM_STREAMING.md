# Multi-platform Streaming Guide

**Author:** Manus AI  
**Scope:** Facebook, YouTube, and custom RTMP/RTMPS destinations  

## Overview

The platform now sends one continuously encoded H.264/AAC broadcast to **Facebook plus any enabled YouTube or custom RTMP/RTMPS destinations**. It uses FFmpeg's tee muxer to distribute the encoded packet stream to multiple outputs, while per-output FIFO queues keep a slow or temporarily unavailable destination from intentionally stopping the remaining outputs.[1]

> The destination key is encrypted before it is written to SQLite. The web API, dashboard, status endpoint, and application log output do not return the original key.

| Capability | Behavior |
|---|---|
| Facebook | Always included when a broadcast starts; the application creates and closes the Facebook Live session. |
| YouTube | Add the YouTube server URL `rtmp://a.rtmp.youtube.com/live2` and the stream key supplied by YouTube Studio. |
| Custom RTMP/RTMPS | Add any server URL beginning with `rtmp://` or `rtmps://`, together with its stream key. |
| Failure isolation | FFmpeg is configured to ignore a failing output and uses FIFO recovery attempts so other destinations can continue. |
| Playlist handling | The playlist loops continuously through FFmpeg's concat demuxer. Input files should use compatible stream characteristics for predictable concat behavior.[1] |
| Destination changes | Add, edit, enable, disable, or delete destinations only while the broadcast is stopped. The next broadcast loads the enabled set. |

## Add a Destination

Open **Settings → Multi-platform Destinations**. Enter a recognizable name, choose **YouTube** or **Custom RTMP / RTMPS**, add the server URL, and paste the destination's stream key. Select **Add destination**. The interface intentionally does not redisplay a saved key; editing requires entering the key again.

The dashboard lists enabled destinations and shows their in-process state during an active stream. A status of **recovering** means the FFmpeg encoder stopped and is following exponential-backoff recovery. A status of **streaming** indicates that the shared FFmpeg process is active; platform-side analytics remain the authoritative source for viewer counts and end-to-end delivery confirmation.

## Required Configuration

Before adding the first destination, set two stable, distinct random environment values. Generate them with the following command twice:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

```ini
SECRET_KEY=first_random_value_at_least_32_characters_long
DESTINATION_ENCRYPTION_KEY=second_random_value_at_least_32_characters_long
```

`DESTINATION_ENCRYPTION_KEY` must remain unchanged after destinations are saved. If it is changed or lost, existing keys cannot be decrypted and must be entered again.

## Operational Notes

| Scenario | Expected result | Operator action |
|---|---|---|
| An extra RTMP target is offline | The target's FIFO output retries; other outputs are configured to continue. | Verify the target URL/key and inspect `logs/ffmpeg.log`. |
| FFmpeg itself exits | The application retries the full encoder using exponential backoff, up to ten attempts. | Check system capacity, input media, connectivity, and FFmpeg logs. |
| A Facebook session nears its duration limit | The application rotates to a new Facebook Live session before the configured limit. | Expect a new Facebook Live ID; external outputs are reconnected by the restarted encoder. |
| Multiple Gunicorn workers are used | Stream control can be duplicated because the scheduler and FFmpeg controller are held in process memory. | Keep the supplied service at **one worker** with threads enabled. |
| Playlist videos differ materially | The concat demuxer can show timing or compatibility issues because inputs are expected to have matching streams. | Transcode videos to a consistent codec, resolution, frame rate, and audio format before upload.[1] |

## Verification

Run the full automated suite after deployment:

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

The tests cover encryption at rest, stream-key non-disclosure from the API, RTMP URL validation, destination enable/disable behavior, tee output construction, and the Settings page controls. The FFmpeg tee/FIFO syntax was also validated against the installed FFmpeg build.

## References

[1]: https://ffmpeg.org/ffmpeg-formats.html#tee "FFmpeg Formats Documentation — tee and concat demuxers"
