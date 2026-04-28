# Rhythm Analyzer

This app provides percussion analysis to improve the precision of performance.
It is running and available for public use via the Plotly/Dash cloud server: visit 
[this page](https://2e7b9ba9-3380-4afa-b92e-f1ff3eee1007.plotly.app/#). It is expected to work in the common modern browsers.

## Practical considerations

App performance is satisfactory with most Wi-Fi connections but may be unsatisfactory 
with a cellular data connection. Recording and playback are done via the browser, with 
audio sent to the `plotly.app` server for analysis and display (except for the local 
server possibility mentioned below). The basic metronome functionality is 
independent of the server once the app page is loaded.

Browsers need permission to use the microphone. It is usually possible, via an 
appropriate setting, for the browser to remember this permission for the `plotly.app` 
domain so it does not need to be granted each time the app is loaded.
- In Chrome: when the permission dialog appears on first visiting or restarting the 
  `plotly.app` page, click Allow. 
- In Safari: `Settings > Websites > Microphone > ...plotly.app > Allow`

Recording length is limited to 10 minutes. Recording stops automatically then, with 
an alerting tone. A variety of factors make 
longer recordings problematic, especially with mobile devices. 

Due to variations in system performance, indicated timing errors 
of about 10 ms (milliseconds), or even more on some systems, are not significant. 
Running a few test in which just the metronome is recorded will 
give an idea of this variability on your system. 
Performance may be better on a computer than a mobile device. 

For best performance, the technically proficient may download the app from its 
[GitHub repository](https://github.com/chaynes56/Rhythm) and run it locally,
instead of relying on the `plotly.app` server.

## Analysis interpretation

The Analysis section is of primary interest, but waveform 
inspection may be useful and permits limiting of analysis to a desired interval.
A mouse (or touch) drag in the waveform selects a portion 
for zoomed display and the statistics are recomputed for that segment of time. 
To return to the full waveform, double click the display or tap the home button in 
the zoom toolbar above the legend to the right of the waveform. 

Good performance is indicated when all four statistics are relatively small. While 
the mean might be considered the primary measure, if a small percentage of pulses 
are way off that will effect the mean more than the median. If the mean and median 
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
- **Exercise**: A named sequence of patterns. These patterns may have differing 
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
single pattern and a number of patterns are a single measure. When using a local 
server, it is possible to create custom exercises and additional voicing codes by 
editing `patterns.py`.
 
## Credits and comments

Thanks to Julian Douglas of [RhythmArise](https://rhythmarise.com/) for the 
[patterns](https://rhythmarise.com/rhythm-vocabulary/). 

Please report any issues or suggestions to the [issue tracker](https://github.com/chaynes56/Rhythm/issues).