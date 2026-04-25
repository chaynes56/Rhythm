# Rhythm Analyzer

This app provides percussion analysis to improve the precision of performance.
It is running and available for public use in the Plotly/Dash cloud: visit 
[this page](https://2e7b9ba9-3380-4afa-b92e-f1ff3eee1007.plotly.app/#). 
At first, it may take up to a minute or so for the server to start up.

App performance is satisfactory with most Wi-Fi connections but may be unsatisfactory 
with a cellular data connection.

Browsers need permission to use the microphone:
- In Chrome: on first visiting the plotly site, when the permission dialog appears 
  click Allow. 
- In Safari: Settings > Websites > Microphone > ...plotly.app > Allow

The metronome plays a low tone at the start of each pattern, a mid-tone at the start 
of each measure (that does not also start a pattern), and optionally a high tone 
on each beat that does not start a measure.

The Analysis section is generally of more interest than the waveform, but waveform 
inspection may be useful. A mouse (or touch) drag in the waveform selects a portion 
for zoomed display and the statistics are recomputed for that segment of time. 
To return to the full waveform, double click the display or tap the home button in 
the zoom toolbar above the legend to the right of the waveform.  

Recording length is limited to 10 minutes. A variety of factors make 
longer recordings problematic, especially with mobile devices. 

Thanks to RhythmArise for the [patterns](https://github.com/RhythmArise/Patterns). 

Please report any issues or suggestions to the [issue tracker](https://github.com/chaynes56/Rhythm/issues).