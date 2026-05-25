# MDA-archivetool
An data scraper and timelapse tool for seb.draws.things project themilliondollardrawing.com.

Options:
For getting the raw picture, run milliondollarartwork.py

For getting data:
First, run scrape_painting.py. It should output a csv file.
Next, run either timelapse tool.
It should automatically find the latest file and make a timelapse.

Arguments (only applicable to clean version for now):

```
usage: 2_timelapse_painting_clean.py [-h] [-fps FPS] [-speed SPEED] [-x0 X0] [-y0 Y0] [-x1 X1] [-y1 Y1] [-scale SCALE]
                                     [-lossless] [-bgcolor BGCOLOR]

options:
  -h, --help        show this help message and exit
  -fps FPS          The fps of your video (default is 60)
  -speed SPEED      The speed of the timelapse in hours per second (default is 1)
  -x0 X0            Region left edge (inclusive)
  -y0 Y0            Region top edge (inclusive)
  -x1 X1            Region right edge (exclusive)
  -y1 Y1            Region bottom edge (exclusive)
  -scale SCALE      Scale factor for output (e.g. 10 = 10x bigger)
  -lossless         Makes it lossless and clean (just type -lossless
  -bgcolor BGCOLOR  Hex Color Of background. (default: #1E1E1E)
```

For any questions or pull requests, just inform me hehe
