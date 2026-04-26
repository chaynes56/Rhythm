# Rhythm Analyzer

This app provides percussion analysis to improve the precision of performance.
It is running and available for public use via the Plotly/Dash cloud server: visit 
[this page](https://2e7b9ba9-3380-4afa-b92e-f1ff3eee1007.plotly.app/#).

App performance is satisfactory with most Wi-Fi connections but may be unsatisfactory 
with a cellular data connection.

Browsers need permission to use the microphone:
- In Chrome: when the permission dialog appears on first visiting or restarting the 
  `plotly.app` page, click Allow. 
- In Safari: `Settings > Websites > Microphone > ...plotly.app > Allow`

The metronome plays a low tone at the start of each pattern, a mid-tone at the start 
of each measure (that does not also start a pattern), and optionally a high tone 
on each beat that does not start a measure.

The Analysis section is of primary interest, but waveform 
inspection may be useful and permits limiting of analysis to a desired interval.
A mouse (or touch) drag in the waveform selects a portion 
for zoomed display and the statistics are recomputed for that segment of time. 
To return to the full waveform, double click the display or tap the home button in 
the zoom toolbar above the legend to the right of the waveform. 

Good performance is indicated when all four statistics are relatively small. While 
the mean might be considered the primary measure, if a small percentage of pulses 
are way off that will effect the mean more than the median. If the mean and median 
are fairly large while the standard deviation is small, that indicates a consistent 
timing error. 

Due to variations in system performance, indicated timing errors 
of about 10 ms (milliseconds), or even more on some systems, are not significant. 
Running a few test in which just the metronome is recorded will 
give an idea of this variability on your system. 
Performance may be better on a computer than a mobile device. 

For best performance, the 
technically proficient may download the app from its [GitHub repository]( 
https://github.com/chaynes56/Rhythm) and run it locally
(instead of relying on the `plotly.app` server). 
.

Recording length is limited to 10 minutes. Recording stops automatically then, with 
an alerting tone. A variety of factors make 
longer recordings problematic, especially with mobile devices. 

Thanks to Julian Douglas of  [RhythmArise](https://rhythmarise.com) for the [patterns]
(https://github.com/RhythmArise/Patterns). 

Please report any issues or suggestions to the [issue tracker](https://github.com/chaynes56/Rhythm/issues).