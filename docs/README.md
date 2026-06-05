# Rhythm Analyzer

This app provides solo percussion analysis to assist improvement of performance
precision. Version 0.1.6 is running and available for public use via the Plotly/Dash
cloud server at [this page](https://2e7b9ba9-3380-4afa-b92e-f1ff3eee1007.plotly.app/#).

Most common modern browsers may be used, though performance in Safari may be
unsatisfactory. Mobile devices are much less capable of accurate timing than most laptop
and desktop computers, but some are usable. The App Performance Section below provides
more guidance on which devices, operating systems, browsers and practice environments
are most likely to be satisfactory.

Begin by reviewing the following Practical Considerations section. Then trying out the
app for a while is the best way to become familiar with its basic capabilities. After a
while you will likely run into questions about aspects of the app's many features or
wonder why it does not work well in some circumstances. Then it is time to explore more
of this documentation with some care to understand the apps capabilities and
limitations.

You may return to this page at any time via the
[Help](https://chaynes56.github.io/Rhythm/#/) link at upper right of the app page.

## Practical Considerations

It takes some time to start the `plotly.app` server, so app loading can take of up to a
minute when first visiting the page. After a fairly long period of inactivity
(perhaps 15 minutes), the server may go to sleep. When that happens much of the app's
functionality will be lost, and it is necessary to refresh or revisit the app's browser
page.

After the app is loaded, there are several additional seconds in which the Start
Recording and Calibration buttons say `Warming up...` and are unresponsive. This allows
time for the audio software to stabilize before being used.

App performance is satisfactory with most Wi-Fi connections but may be unsatisfactory
with a cellular data connection. The server sends metronome and exercise tracks to the
browser and the browser sends recordings back to the server.

It is necessary to grant permission for the
`plotly.app` domain to use the microphone. Via an appropriate privacy setting it is
usually possible to avoid having to do this every time the app is loaded. For example,
in Chrome when the permission dialog appears on first visiting or restarting the
`plotly.app` page, click `Allow` or `Allow always` or `Forever`.

Recording length is limited to 10 minutes, at which point it stops automatically with an
alerting tone.

Starting a recording starts the metronome as well, with a few seconds of metronome beats
before the recording begins. This is similar to a conductor counting in the orchestra.

## Analysis Interpretation

At risk of stating the obvious: though precision timing is an essential percussion
skill, musical expression may include subtle timing deviations that this app cannot
distinguish from unintentional timing errors.

All analysis is reported as millisecond (ms) deviations of each detected pulse from the
"ideal" timing established by the metronome. A positive deviation indicates the pulse
was late.

Deviations are color coded according to the `Training Level` selected: `Novice`,
`Intermediate`, or `Advanced`. An expert may detect timing deviations of as little as 5
ms, while a deviation of 15 ms is apparent to most listeners. Thus, deviations of less
than 5 ms are indicated in green at the expert level, while deviations less than 15 ms
are green at the beginner level and the green threshold for intermediate is 10 ms.
Deviations up to twice the green cutoff are orange and over that are red.

The app's analysis section provides a variety of perspectives on timing deviations,
which are detailed later in this section. However, it is first important to be aware of
the ways in which the accuracy of this analysis may be compromised by three distinct
sources of timing errors.

1. Stability of play and record timing: This seldom creates problems, which in any case
   cannot be improved by the app. System configurations that are identified as highly
   problematic in the performance section below may result in this type of error.
2. Synchronization of metronome play and recording: This is the purpose of the app's
   calibration mechanisms, which sometimes calls for user interaction. See the
   calibration section below.
3. Pulse detection, which also places the onset of each detected pulse at an appropriate
   instant in time. While attention has been paid to this in the app's design, there is
   at present no provision for user interaction to improve it further. Be aware that
   stray noises that are sufficiently loud may be detected as pulses, and tones that are
   too soft will not be detected. Also, the voicing of tones may affect the point in
   time assigned to them, which in turn affects the magnitude of reported timing errors.
   Determining the exact time assigned to a pulse is an imperfect science, in which
   subjective perception plays a role.

The waveform at the top of the analysis section can be useful for investigating problems
such as those mentioned in point 3 above. Little diamond and tick marks above indicate
metronome beat and subdivision timing, respectively, with beat color significance
indicated by the diamond color in accordance with the key at right. The green diamonds
below indicate detected pulse times. A mouse or touch drag in the waveform selects a
portion of time for display, and statistics are recomputed for that segment of time. To
return to the full recording, double-click the display or tap the home button in the
zoom toolbar above the legend to the right of the waveform. Along with the waveform a
pink onset envelope is displayed. Beat detection occurs when the onset envelope exceeds
the threshold indicated by the horizontal pink line. Deviations from metronome timing of
each detected pulse are indicated in the bar graph below the waveform. Note especially
trends that indicate timing drift. A sudden flip from a large positive to a large
negative values, or vice versa, is characteristic of a drift from one subdivision to
another. The bar graph also includes blue dots that indicate the timing relative to the
previous pulse, with the x-axis representing the perfect subdivision interval.

The first statistics presented in the text area are the number of pulses and beats in
the selected interval. When recording just the metronome, these should be the same. When
recording a pattern or exercise, the ratio of pulses to beats in the pattern should be
close to the indicated pulse to beat ratio. A few missed pulses have little effect on
the statistics; excess pulse detections indicate a problem with the recording. The
number of ms per subdivision (the shortest possible intended interval between pulses)
is provided as a point of comparison.

Good performance is indicated when all four following statistics are relatively small.
While the mean might be considered the primary measure, if a small percentage of pulses
are way off that will affect the mean more than the median. If the mean and median are
large while the standard deviation is small, that indicates a consistent timing error.
The max (maximum) is how far off your worst pulse was, unless that pulse was off by more
than half the subdivision length, in which case it will be computed as deviation from
the wrong subdivision.

### Interval and Spectrum analysis

TODO: TABLE AND HISTOGRAM INTERPRETATION

## Rhythm Units and Constraints

- **Subdivision**: The unit of time used for analysis. From 1 to 6 subdivisions per beat
  may be selected (default is 4).
- **Beat**: The basic unit of metronome time, indicated optionally by a high tone unless
  it begins a measure or pattern.
- **Measure**: 1 to 16 beats (default is 4), with the first indicated optionally by a
  metronome mid-tone, unless it begins a pattern. The maximum number of subdivisions per
  measure is 32.
- **Pattern**: 1 to 8 measures (default is 4), beginning with a metronome low tone, all
  with the same beats/measure and subdivisions/beat.
- **Exercise**: (NOT YET IMPLEMENTED) A named sequence of patterns. These patterns may
  have differing beats/measure and subdivisions/beat. For each exercise pattern a line
  is displayed in the metronome section identifying each subdivision and beat, followed
  by a line for each measure of the pattern indicating which subdivisions are voiced,
  with intonation indicated by a letter. Odd numbered columns within a pattern,
  typically played with the non-dominant hand, are shaded gray.

  If no exercise is selected, only a line per measure of metronome beat indicators
  (see section below) is displayed. In both cases beats are highlighted as they are
  played (or reached silently) by the metronome. There is an option to play a higher
  tone (always the same) when each voiced subdivision is reached.

  This complexity allows more advanced exercises, but most exercises are a single
  pattern, and a number of patterns are a single measure.

The metronome works by pre-computing an entire metronome cycle, after which the selected
exercise (or pattern if no exercise has been selected) is repeated. Resource constraints
limit the length of this cycle to 5 minutes. This limit cannot be exceeded with the
basic metronome options; only with long exercises at a sufficiently slow tempo. If an
exercise is selected that would exceed the limit at the current tempo, the selection
will be rejected with an alert.

## Calibration

## App Performance Issues

For the metronome **beat indicator** (the highlighted box that advances with each beat)
to synchronized to the audio output and recording analysis to be reasonably accurate,
the app needs to know the latency of the browser's audio input and output. Though
typically stable within a few milliseconds (ms), this latency may be substantial and is
highly dependent on unpredictable characteristics of the browser and the operating
system resources it is allocated. To compensate for this, the app performs a calibration
by playing several metronome beats when it starts. If headphones are used, it is
important that they be placed very near the microphone during this calibration.

Ambient noise during calibration or an exceptionally long browser audio chain warmup
period may cause this initial calibration to be inaccurate. If in doubt, run a test
recording of just the metronome and check that the analysis indicates errors of at most
a few ms. If necessary, calibration may be repeated by clicking the **Calibrate**
button.

On most wired or built-in audio devices the metronome indicator and the audible beat
will align closely, and recording analysis will be accurate to within a few ms.
**Bluetooth audio devices** introduce additional buffering time (typically 100–500 ms,
sometimes more). A Bluetooth microphone is not recommended. Bluetooth speakers or
headphones may be satisfactory if buffering delay is stable.

It is possible that a VPN may introduce additional latency or other issues. Reports of
experience in this regard are welcome via the issue tracker mentioned below.

## Saving, loading and listening to recordings

TODO: finish this section

## Settings

The Settings dropdown provides options for saving and loading settings, and restoring
the default settings. The settings include all the user's selections in the app. These
are automatically saved in the browser's *local storage*, and restored when the app is
restarted in the same browser, so many users will not need to routinely use these manual
save and load options. Situations where manual saving and loading of settings will be
useful include:

- Switching between different practice contexts that require multiple setting changes
- Switching between browsers or devices, which never share local storage
- As a way of loading custom exercises or enabling debug mode, which cannot be done via
  the graphic user interface

When Save Settings is selected in the dropdown, a file named `rhythm-settings.yaml`
is stored in the browser's default download folder (typically `Downloads` or `My 
Documents`) in YAML format. The Load Settings button restores the settings from the
selected `.yaml` file. *It is essential that modification of a YAML file be done with a
plain-text editor, or the file will be corrupted.*

### Debug mode

The default is `debug-mode: false`. If `false` is replaced with `true` and the settings
file then loaded, additional information will be provided in the browser interface and
the browser and server logs that may assist debugging. This change is not persistent: it
will not automatically be made when new settings are saved and reverts to the default
when the app page is revisited.

### Custom exercises

By editing the YAML file with a plain-text editor, it is possible to create custom
exercises, which appear at the start of the dropdown exercise list. Here is an example.

```text
custom-exercises: |-
  My groove
  1e&a2e&a3e&a4e&a
  B.s..Bh...l....h
  ----
  3/4 to 4/4
  1&a2&a3&a
  BxxBxxBxx
  1e&a2e&a3e&a4e&a
  BxxxBxxxBxxxBxxx
```

The general syntax for exercises is a bit complex, but it allows for a wide variety of
exercises and is best grasped by following this example. The custom exercises setting is
at the end of the YAML file and begins initially with
`custom-exercises: ''`. To create custom exercises, change the `''` to `|-`
and add following lines defining your own exercises. These lines must all be indented by
two spaces (tabs not allowed).

The exercises are separated by a line with four dashes (`----`). Each exercise consists
of a name line followed by one or more patterns.

- Each *pattern* begins with a subdivision line, which defines a time signature,
  followed by one or more measure lines.
- A *subdivision line* consists of sequential beat integers, starting with 1, separated
  by one letter for each additional subdivision of the beat. (The example uses a common
  convention for subdivision letters, but any letter that is not a number may be used.)
- A *pattern line* is a sequence of voicing character that line up with the
  corresponding subdivision's letters or beat integer. Multiple pattern lines in a
  measure line group share the same subdivision line.
- A *voicing character* is one of those in the following key, which also indicates the
  common name: `x: any, B: base, l: low, h: high, s: slap, t: tone, F: flam, m: mute,
   q: quiet, .: ghost note`.

## Local server

The technically proficient may download the app from its
[GitHub repository](https://github.com/chaynes56/Rhythm) and run it locally (on your own
computer) instead of relying on the `plotly.app` server. This might result in better
performance.

## Issues and Suggestions

Please report instances in which errors are reported (in red) along with any quoted
details, unless of course the problem is due to known issues in your environment.
Reports of unsatisfactory performance are also welcome if they cannot be explained by
factors detailed in this documentation. Suggestions for improvement are also welcome.
Please submit all such reports using
[this form](https://docs.google.com/forms/d/e/1FAIpQLSe5rD8X_BpVd9I359ZcoiqN-0E0De1JOvnbr7X3xj22Ca96cg/viewform?usp=publish-editor).

## Collaboration and Credits

Those interested in contributing to development of this open source project see the
[development notes](https://chaynes56.github.io/Rhythm/#/DevNotes).

Thanks to Julian Douglas of [RhythmArise](https://rhythmarise.com/) for consultation,
inspiration, voicing tones, and the
[patterns](https://rhythmarise.com/rhythm-vocabulary/).

