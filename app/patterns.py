#!/usr/bin/env python3
# Copyright 2026 Christopher T. Haynes. See the project LICENSE file.

# Thanks to https://rhythmarise.com/rhythm-vocabulary/ for these patterns.

# patterns_text is a sequence of patterns separated by a blank line.
# Each pattern consists of its name line, beat and subdivision line, and one or more
# measure lines.
# Voicing key of pattern pillars: x: any, B: base, l: low, h: high, s: slap,
# blank: ghost note.
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
"""
# TODO add more patterns

# TODO process text
# dict: name -> {num_measures: int, beats_per_measure: int, pattern: list(str)}
patterns = patterns_text
