#!/usr/bin/env python3
# Copyright 2026 Christopher T. Haynes. See the project LICENSE file.

# Thanks to https://rhythmarise.com/rhythm-vocabulary/ for these patterns.

voicing_key = {
    'x': 'any',
    'B': 'base',
    'l': 'low',
    'h': 'high',
    's': 'slap',
    ' ': 'ghost note'
}
# patterns_text is a sequence of patterns separated by a blank line.
# Each pattern consists of its name line followed by one or more measure-line groups.
# Each measure-line group begins with a subdivision line followed by one or more
# pattern lines. A subdivision line consists of sequential beat integers separated
# by one letter for each measure subdivision. A space follows these letters
# for readability unless the beat integer has two digits. A pattern line is a
# sequence of pillars that line up with the corresponding subdivisions letters or
# beat integer. Each pillar is represented by a single character from voicing_key.
# Multiple pattern lines in a measure line group share the same subdivision line.
patterns_text = """
3,3,2 (tresillo)
1 e & a 2 e & a
x     x     x

3,2,3
1 e & a 2 e & a
x     x   x

3/2 Clave
1 e & a 2 e & a 3 e & a 4 e & a
x     x     x       x   x

Gravity Grooves
1 e & a 2 e & a 3 e & a 4 e & a
B
B   B
B B B
B                           B
B                           B B

Susan's Groove
1 e & a 2 e & a 3 e & a 4 e & a 5 e & a 6 e & a 7 e & a 8 e & a
B   h       h   B   h B     h h B   h       h   B B B B B   h h

Pulses
1 & a 2 & a 3 & a 4 & a
B x x B x x B x x B x x
1 e & a 2 e & a 3 e & a 4 e & a
B x x x B x x x B x x x B x x x
1 & 2 & 3 & 4 & 5 & 6 &
B x B x B x B x B x B x
"""
# TODO add more patterns

# TODO process text
# dict: name -> list(measure_group)
# measure_group: { beats: int,
#                  subdivisions_per_beat: int,
#                  patterns: list(pattern_string)
#                }
# pattern_string: sequence of voicing characters
patterns = patterns_text
