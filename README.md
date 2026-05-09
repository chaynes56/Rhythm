# Rhythm Analyzer

This app provides percussion analysis to improve the precision of performance.
It is running and available for public use via the Plotly/Dash cloud 
server: just visit 
[this page](https://2e7b9ba9-3380-4afa-b92e-f1ff3eee1007.plotly.app/#). 
It is expected to work in all the common modern browsers.

An intuitive understanding of the app may suffice, but the following information is
provided for a fuller understanding of the app's capabilities, how best to interpret 
its performance analysis, and its limitations in certain circumstances.

You may return to this page at any time via the 
[Help](https://github.com/chaynes56/Rhythm) link at upper right of the app page. 

## Practical considerations

It takes time to start a `plotly.app` server, so app loading can take of up a to 
minute or so when first visiting the page. After a fairly long period of inactivity
(perhaps 15 minutes or so), the server may go to sleep. When that happens much of 
the app's functionality will be lost, and it is necessary to refresh or revisit the 
app's browser page. The app settings will then revert to their defaults. 
If this is a recurring issues, use the save settings option described below. 

App performance is satisfactory with most Wi-Fi connections but may be unsatisfactory 
with a cellular data connection. Recording and playback are done via the browser, with 
audio sent to the server for analysis.

Browsers need permission to use the microphone. It is usually possible, via an 
appropriate setting, for the browser to remember this permission for the `plotly.app` 
domain so it does not need to be granted each time the app is loaded.
- In Chrome: when the permission dialog appears on first visiting or restarting the 
  `plotly.app` page, click Allow. 
- In Safari: `Settings > Websites > Microphone > ...plotly.app > Allow`

Recording length is limited to 10 minutes, at which point it stops 
automatically with an alerting tone. Practical considerations also limit the length
of a metronome exercise or pattern to be at most 5 minutes. 

Starting a recording starts the metronome as well, with one measure of metronome before
the recording actually begins. This is similar to a conductor counting in the 
orchestra, and allows the performer to get into the rhythm before the recording 
starts.

## Analysis interpretation

A mouse or touch drag in the waveform selects a portion of time for display, and 
statistics are recomputed for that segment of time. 
To return to the full recording, double-click the display or tap the home button in 
the zoom toolbar above the legend to the right of the waveform. Analysis depends on 
relatively accurate determination of pulse timing, which is an imperfect science as 
much depends on the nature of the pulse tone, acoustics, recording and metronome 
audio characteristics, among other factors. Performance analysis is necessarily a 
function of both the player's timing and the accuracy of pulse detection.

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
vice versa, is characteristic of a drift from one subdivision to another. 

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
- **Exercise**: (NOT YET IMPLEMENTED) A named sequence of patterns. These patterns may 
  have differing beats/measure and subdivisions/beat. For each exercise pattern a line 
  is displayed in the metronome section identifying each subdivision and beat, 
  followed by a line for each measure of the 
  pattern indicating which subdivisions are voiced, with intonation indicated by a 
  letter. Odd numbered columns within a pattern, typically played with the 
  non-dominant hand, are shaded gray.

  If no exercise is selected, only a line per measure of metronome beat indicators
  (see section below) is displayed. In both cases beats are highlighted as they are 
  played (or reached silently) by the metronome. There is an option to play a higher 
  tone (always the same) when each voiced subdivision is reached.    

  This complexity allows more advanced exercises, but most exercises are a 
  single pattern, and a number of patterns are a single measure. 

## Audio latency

For the metronome **beat indicator** (the highlighted box that advances with each beat) 
to synchronized to the audio output and recording analysis to be reasonably accurate, 
the app needs to know the latency of the browser's audio input and output. 
Though typically stable within a few milliseconds (ms), this latency may be substantial 
and is highly dependent on unpredictable characteristics of the browser and the
operating system resources it is allocated. To compensate for this, the app
performs a calibration by playing several metronome beats when it starts. 
If headphones are used, it is important that they be placed very near the microphone 
during this calibration. 

Ambient noise during calibration or an exceptionally long browser audio chain 
warmup-up period may cause this initial calibration to be inaccurate. If in doubt, 
run a test recording of just the metronome and check 
that the analysis indicates errors of at most a few ms. If necessary, 
calibration may be repeated by clicking the **Calibrate** button.

On most wired or built-in audio devices the metronome indicator and the audible beat 
will align closely, and recording analysis will be accurate to within a few ms. 
**Bluetooth audio devices** introduce additional buffering time (typically 100–500 ms, 
sometimes more). A Bluetooth microphone is not recommended. Bluetooth speakers 
or headphones may be satisfactory if buffering delay is stable. 

It is possible that a VPN may introduce additional latency or other issues.
Reports of experience in this regard are welcome via 
the issue tracker mentioned below.

## Settings

The Save Settings button stores the current settings in the browser's default 
download folder (typically `Downloads` or `My Documents`) in YAML format. 
The Load Settings button restores the settings from the selected `.yaml` file.

### Custom exercises
By editing the YAML file with a plain-text editor, it is possible to create custom 
exercises, which appear at the start of the dropdown exercise list. Here is an example.

```text
custom-exercises: |-
  My groove
  1e&a2e&a3e&a4e&a
  B.x..Bh...l....h
  ----
  3/4 to 4/4
  1&a2&a3&a
  BxxBxxBxx
  1e&a2e&a3e&a4e&a
  BxxxBxxxBxxxBxxx
```

The general syntax for exercises is a bit complex, but it allows for a wide variety of
exercises and is best grasped by following this example. 
The custom exercises setting is at the end of the YAML file and begins with the line
`custom-exercises: |-`. The following lines defining the custom exercises must 
all be indented by two spaces (tabs not allowed). 

The exercises are separated by a line with four dashes (`----`). Each exercise 
consists of a name line followed by one or more patterns.
- Each *pattern* begins with a subdivision line, which defines a time 
  signature, followed by one or more measure lines. 
- A *subdivision line* consists of sequential beat integers, starting with 1, separated
  by one letter for each additional subdivision of the beat. (The example uses a 
  common convention for subdivision letters, but any letter that is not a number may 
  be used.)
- A *pattern line* is a
  sequence of voicing character that line up with the corresponding subdivision's
  letters or beat integer. Multiple pattern lines in a measure line group share the
  same subdivision line.
- A *voicing character* is one of those used in the example and indicates the 
  intonation of the subdivision, or a period (`.`) to indicate a ghost note (rest).

## Local server

The technically proficient may download the app from its 
[GitHub repository](https://github.com/chaynes56/Rhythm) and run it locally (on your 
own computer) instead of relying on the `plotly.app` server. This might result in 
better performance. 

## Credits and comments

Thanks to Julian Douglas of [RhythmArise](https://rhythmarise.com/) for the [patterns](https://rhythmarise.com/rhythm-vocabulary/). 

Please report any issues or suggestions to the [issue tracker](https://github.com/chaynes56/Rhythm/issues).