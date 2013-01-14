Spotter : Unsophisticated video tracking
========================================

[Spotter](http://wonkoderverstaendige.github.com/Spotter) can track LEDs in a video stream--either from a webcam or video file--and simultaneously write encoded video to disk. It is based on the [OpenCV](http://opencv.org/) library. It's a very early alpha and hardly working.


Simple Example
--------------

    python spotter.py --source video.avi

or

    python spotter.py --source 0 --outfile result.avi --dims 640x360 --fps 15

Requirements
------------

Tested on Windows 7 64bit, (X)Ubuntu 12.04 64bit

- Python 2.7+
- OpenCV 2.4+
- docopt 0.5+
- pySerial

Future
------

Position information and crossing of ROIs will be sent to a microcontroller via serial port.
