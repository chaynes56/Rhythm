# Rhythm Analyzer

This app provides percussion analysis to improve the precision of performance.
It is running and available for public use via the Plotly/Dash cloud 
server: just visit 
[this page](https://2e7b9ba9-3380-4afa-b92e-f1ff3eee1007.plotly.app/#). 
It is expected to work in all the common modern browsers.

You may return to this page at any time via the 
[Help](https://github.com/chaynes56/Rhythm) link at upper right of the app page. 

## Practical considerations

It takes time to start a plotly.app server, so app loading takes a minute or so, and 
after the first recording analysis takes several seconds while additional 
resources are loaded.

App performance is satisfactory with most Wi-Fi connections but may be unsatisfactory 
with a cellular data connection. Recording and playback are done via the browser, with 
audio sent to the `plotly.app` server for analysis.

Browsers need permission to use the microphone. It is usually possible, via an 
appropriate setting, for the browser to remember this permission for the `plotly.app` 
domain so it does not need to be granted each time the app is loaded.
- In Chrome: when the permission dialog appears on first visiting or restarting the 
  `plotly.app` page, click Allow. 
- In Safari: `Settings > Websites > Microphone > ...plotly.app > Allow`

Recording length is limited to 10 minutes, at which point it stops 
automatically with an alerting tone.

## Analysis interpretation

A mouse or touch drag in the waveform selects a portion of time for display, and 
statistics are recomputed for that segment of time. 
To return to the full recording, double-click the display or tap the home button in 
the zoom toolbar above the legend to the right of the waveform. 

Performance analysis is provided in the form of statistics related to the deviation 
in milliseconds (ms) from the expected timing.
Timing errors of up to 10 ms, or even more on some 
systems, may be expected due to variations in system 
performance. Running a few tests in which just the metronome is recorded will 
give an idea of this variability on your system. 
Performance may be better on a computer than a mobile device. Actual performance 
variation of less than 5 ms is excellent, 10 ms is very good, and more than 15 ms 
is often noticeable.  

Timing errors are indicated in the bar graph below the waveform, and as summary 
statistics in the Analysis section below the waveform. The Training Level selected
determines the color-coding thresholds. In the bar graph, note especially trends 
that indicate timing drift. A sudden flip from large positive to negative values, or 
visa versa, is characteristic of a drift from one subdivision to another. 

The first statistics presented in the text area 
are the number of pulses and beats in the selected interval.
When recording just the metronome, these should be the same. When recording a 
pattern, the ratio of pulses to beats in the pattern should be close to the 
indicated pulse to beat ratio. A few missed pulses have little effect on the 
statistics; excess pulse detections indicate a problem with the recording. The 
number of ms per subdivision (the shortest possible intended interval between pulses)
is provided as a point comparison.  

Good performance is indicated when all four following statistics are relatively small. 
While the mean might be considered the primary measure, if a small percentage of pulses 
are way off that will affect the mean more than the median. If the mean and median 
are while the standard deviation is small, that indicates a consistent 
timing error. The maximum is how far off your worst pulse was, unless that pulse
was off by more than half the subdivision length, in which case it will be computed as 
deviation from the wrong subdivision.  

## Rhythm units and constraints

- **Subdivision**: The unit of time used for analysis. From 1 to 6 subdivisions per 
  beat may be selected (default is 4).
- **Beat**: The basic unit of metronome time, indicated optionally by a high tone 
  unless it begins a measure or pattern.  
- **Measure**: 1 to 16 beats (default is 4), with the first indicated optionally by a 
  metronome mid-tone, unless it begins a pattern. The maximum number of subdivisions 
  per measure is 32. 
- **Pattern**: 1 to 8 measures (default is 4), beginning with a metronome 
  low tone, all with the same beats/measure and subdivisions/beat.
- **Exercise**: (Under development) A named sequence of patterns. These patterns may 
  have differing 
  beats/measure and subdivisions/beat. For each exercise pattern a line is displayed 
  identifying each subdivision and beat, followed by a line for each measure of the 
  pattern indicating which subdivisions are voiced, with intonation indicated by a 
  letter. Odd numbered columns within a pattern, which are played with the 
  non-dominant hand, are shaded grey.

  If no exercise is selected, only the metronome beat and measures pattern is 
  displayed. In both cases beats are highlighted as they are played (or reached 
  silently) by the metronome. There is an option to play a higher tone (always the 
  same) when each voiced subdivision is reached.    

  This complexity allows more advanced exercises, but most exercises are a 
  single pattern and a number of patterns are a single measure. 

## Local server

The technically proficient may download the app from its 
[GitHub repository](https://github.com/chaynes56/Rhythm) and run it locally (on your 
own computer) instead of relying on the `plotly.app` server. This might result in 
better performance. It is also then possible to create custom exercises and additional 
voicing codes by editing `exercises.py`.

## Credits and comments

Thanks to Julian Douglas of [RhythmArise](https://rhythmarise.com/) for the 
[patterns](https://rhythmarise.com/rhythm-vocabulary/). 

Please report any issues or suggestions to the [issue tracker](https://github.com/chaynes56/Rhythm/issues).