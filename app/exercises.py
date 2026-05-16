#!python3
# Copyright 2026 Christopher T   Haynes   See the project LICENSE file.

# Thanks to https://rhythmarise.com/rhythm-vocabulary/ for the exercises.
#   Julio Llerena shared the Afro-Peruvian groove with the Earthfolk Drum and Dance
#   clinic in 2024.

from pprint import pprint

voicing_code = {  # voicing characters are the keys
    'x': 'any',
    'B': 'base',
    'l': 'low',
    'h': 'high',
    's': 'slap',
    't': 'tone',
    'F': 'flam',
    '.': 'none (ghost note)'
}
voicing_characters = ''.join(list(voicing_code.keys()))

# exercises_text is a sequence of exercises separated by `----`.
# The exercises are separated by a line with three dashes (`----`). Each exercise
# consists of a name line followed by one or more patterns.
# - Each *pattern* begins with a subdivision line, which defines a time
#   signature, followed by one or more measure lines.
# - A *subdivision line* consists of sequential beat integers, starting with 1, separated
#   by one letter for each additional subdivision of the beat. (The example uses a
#   common convention for subdivision letters, but any letter that is not a number may
#   be used.)
# - A *pattern line* is a
#   sequence of voicing character that line up with the corresponding subdivision's
#   letters or beat integer. Multiple pattern lines in a measure line group share the
#   same subdivision line.
EXERCISES_TEXT = """
3,3,2 (tresillo)
1e&a2e&a
x..x..x.
----
3,2,3
1e&a2e&a
x..x.x..
----
2,3,3
1e&a2e&a
x.x..x..
----
2,3,3 Passport
1e&a2e&a
B.ll.hh.
----
3,3,2 Passport
1e&a2e&a
B.lB..h.
----
Upbeat Passport
1e&a2e&a
..ll..hh
----
Binary Groove
1e&a2e&a3e&a4e&a
B...t...B...t...
----
Binary Groove & Floating Accent
1e&a2e&a3e&a4e&a
Bx..t...B...t...
B.x.t...B...t...
B..xt...B...t...
B...tx..B...t...
B...t.x.B...t...
B...t..xB...t...
B...t...Bx..t...
B...t...B.x.t...
B...t...B..xt...
B...t...B...tx..
B...t...B...t.x.
B...t...B...t..x
----
Gravity Grooves
1e&a2e&a3e&a4e&a
B...............
B.B.............
BBB.............
B.............B.
B.............BB
----
3/2 Clave
1e&a2e&a3e&a4e&a
x..x..x...x.x...
----
2/3 Clave
1e&a2e&a3e&a4e&a
..x.x...x..x..x.
----
Brazilian Clave (Bossa Nova Stick Pattern)
1e&a2e&a3e&a4e&a
..x.x...x..x..x.
----
Rumba Clave
1e&a2e&a3e&a4e&a
x..x...x..x.x...
----
7/9
1e&a2e&a3e&a4e&a
x.x.x..x.x.x.x..
----
cascara
1e&a2e&a3e&a4e&a
x.x.xx.xx.xx.x.x
----
cicada
1e&a2e&a3e&a4e&a
x.x..xxx.xxx.x.x
----
Fanga
1e&a2e&a3e&a4e&a
B.ll.hh.B.B.hh..
----
Baladi
1e&a2e&a3e&a4e&a
B.B.lll.B.lll.hh
----
Tumbau
1e&a2e&a3e&a4e&a
..s...ll..sBB.ll
----
montuno
1e&a2e&a3e&a4e&a
B.hB.h.B.h.BB.h.
----
Susan's Groove
1e&a2e&a3e&a4e&a5e&a6e&a7e&a8e&a
B.h...h.B.hB..hhB.h...h.BBBBB.hh
----
7,9 - (8th note resolution)
1e&a2e&a3e&a4e&a5e&a6e&a7e&a8e&a
B...l...h.....B...l...h.....BBBB
----
Pulses
1&a2&a3&a4&a
BxxBxxBxxBxx
1e&a2e&a3e&a4e&a
BxxxBxxxBxxxBxxx
1&2&3&4&5&6&
BxBxBxBxBxBx
----
2/3 Clave (12 box)
1&a2&a3&a4&a
.x.x..x.x.x.
1e&a2e&a3e&a
.x.x..x.x.x.
1&2&3&4&5&6&
.x.x..x.x.x.
----
3/2 Clave Bell Pattern (12 box)
1&a2&a3&a4&a
x.x.xx.x.x.x
1e&a2e&a3e&a
x.x.xx.x.x.x
1&2&3&4&5&6&
x.x.xx.x.x.x
----
4 beat 4x3 passport
1&a2&a3&a4&a
hl.h..hl.h..
h.lh..h.lh..
h..hl.h..hl.
h..h.lh..h.l
hllh..hllh..
h..hllh..hll
h.lhl.h.lhl.
hl.h.lhl.h.l
----
3 beat 4x3 passport
1e&a2e&a3e&a
hl.h..hl.h..
h.lh..h.lh..
h..hl.h..hl.
h..h.lh..h.l
hllh..hllh..
h..hllh..hll
h.lhl.h.lhl.
hl.h.lhl.h.l
----
6 beat 4x3 passport
1&2&3&4&5&6&
hl.h..hl.h..
h.lh..h.lh..
h..hl.h..hl.
h..h.lh..h.l
hllh..hllh..
h..hllh..hll
h.lhl.h.lhl.
hl.h.lhl.h.l
----
4 beat 3x2 passport
1&a2&a3&a4&a
l.l...l.l...
..l.l...l.l.
..l.ll..l.ll
llh...llh...
----
3 beat 3x2 passport
1e&a2e&a3e&a
l.l...l.l...
..l.l...l.l.
..l.ll..l.ll
llh...llh...
----
6 beat 3x2 passport
1&2&3&4&5&6&
l.l...l.l...
..l.l...l.l.
..l.ll..l.ll
llh...llh...
----
Afro-Peruvian groove
1e&a2e&a3e&a
FBB.t.BB.tB.
t.B.Btt.B.Bt
"""


# pattern: { beats_per_measure: int,
#            subdivisions_per_beat: int,
#            measures_per_pattern: int,
#            subdivision_line = str,
#            measures: list(measure_line)
#          }
# measure_line: string of voicing characters of length subdivisions_per_beat *
#   beats_per_measure.
# exercise: { total_beats: int, patterns: list(pattern) }
# exercise_dict: exercise_name -> exercise
def make_exercises(text):  # -> exercise_dict
    exercise_dict = {}
    for exercise_text in text.split('----'):
        lines = exercise_text.strip().splitlines()
        exercise_name = lines[0].strip()
        subdivisions_per_beat = 0
        num_beats = 0
        patterns = []
        measures = []  # avoid reference before assignment warning
        for line in lines[1:]:
            def error(message):
                raise ValueError(
                    f"{message} in exercise {exercise_name!r} line {line!r}"
                )

            line = line.strip()
            if not line:  # end of exercise
                break
            if line[0] == '1':  # start a pattern
                measures = []
                beat1, _ = line.split('2')
                subdivisions_per_beat = len(beat1)
                if not all(c.isdigit() for c in line[::subdivisions_per_beat]):
                    error('invalid subdivision line beat number')
                num_beats = int(len(line) / subdivisions_per_beat)
                if len(line) % subdivisions_per_beat != 0:
                    error('invalid subdivision line length')
                patterns.append(
                    {'beats_per_measure': num_beats,
                     'subdivisions_per_beat': subdivisions_per_beat,
                     'subdivision_line': line,
                     'measures': measures
                     })
            else:
                if not all(c in voicing_characters for c in line):
                    # characters with even index must be voicing codes
                    error('invalid voicing code')
                elif len(line) != subdivisions_per_beat * num_beats:
                    error('invalid pattern line length')
                measures.append(line)
        total_beats = sum(pat['beats_per_measure'] * len(pat['measures'])
                          for pat in patterns)
        exercise_dict[exercise_name] = {'total_beats': total_beats,
                                        'patterns': patterns}
    return exercise_dict


exercises = make_exercises(EXERCISES_TEXT)

if __name__ == '__main__':
    pprint(exercises)
    print('Done')
