#!/usr/bin/env python3
# Copyright 2026 Christopher T. Haynes. See the project LICENSE file.

# Thanks to https://rhythmarise.com/rhythm-vocabulary/ for these patterns.

from pprint import pprint

voicing_code = {  # voicing characters are the keys below
    'x': 'any',
    'B': 'base',
    'l': 'low',
    'h': 'high',
    's': 'slap',
    ' ': 'ghost note'
}
voicing_characters = ''.join(list(voicing_code.keys()))

# exercises_text is a sequence of patterns separated by `---`.
# Each pattern consists of its name line followed by one or more measure-line groups.
# Each measure-line group begins with a subdivision line followed by one or more
# pattern lines. A subdivision line consists of sequential beat integers separated
# by one letter for each measure subdivision. A space follows these letters
# for readability unless the beat integer has two digits. A pattern line is a
# sequence of pillars that line up with the corresponding subdivisions letters or
# beat integer. Each pillar is represented by a voicing character other than space.
# Multiple pattern lines in a measure line group share the same subdivision line.
# TODO add more patterns
exercises_text = """
3,3,2 (tresillo)
1 e & a 2 e & a
x     x     x
---
3,2,3
1 e & a 2 e & a
x     x   x
---
3/2 Clave
1 e & a 2 e & a 3 e & a 4 e & a
x     x     x       x   x
---
Gravity Grooves
1 e & a 2 e & a 3 e & a 4 e & a
B
B   B
B B B
B                           B
B                           B B
---
Susan's Groove
1 e & a 2 e & a 3 e & a 4 e & a 5 e & a 6 e & a 7 e & a 8 e & a
B   h       h   B   h B     h h B   h       h   B B B B B   h h
---
Pulses
1 & a 2 & a 3 & a 4 & a
B x x B x x B x x B x x
1 e & a 2 e & a 3 e & a 4 e & a
B x x x B x x x B x x x B x x x
1 & 2 & 3 & 4 & 5 & 6 &
B x B x B x B x B x B x
"""


# measure_group: { beats: int,
#                  subdivisions_per_beat: int,
#                  subdivision_line = str,
#                  patterns: list(pattern_string)
#                }
# pattern_string: string of voicing characters of length subdivisions_per_beat * beats
# exercise_dict: exercise_name -> list(measure_group)
def make_exercises(text):  # -> (list(exercise_name), exercise_dict)
    exercise_name_list = []
    exercise_dict = {}
    for exercise_text in text.split('---'):
        lines = exercise_text.strip().splitlines()
        exercise_name = lines[0].strip()
        exercise_name_list.append(exercise_name)
        measure_group_list = []
        subdivisions_per_beat = 0
        num_beats = 0
        patterns = []
        for line in lines[1:]:
            def error(message):
                raise SystemExit(
                    f"Error: {message} in exercise {exercise_name} line {line}"
                )

            line = line.strip()
            if not line:  # end of exercise
                break
            if line[1::2].strip():  # characters with odd index must be blank
                error('even position characters must be blank')
            line = line[::2]  # only use characters with even index
            if line[0] == '1':  # start a measure_group
                patterns = []
                beat1, _ = line.split("2")
                subdivisions_per_beat = len(beat1)
                if not all(c.isdigit() for c in line[::subdivisions_per_beat]):
                    error('invalid subdivision line beat number')
                num_beats = int(len(line) / subdivisions_per_beat)
                if len(line) % subdivisions_per_beat != 0:
                    error('invalid subdivision line')
                measure_group_list.append(
                    {'beats': num_beats,
                     'subdivisions_per_beat': subdivisions_per_beat,
                     'subdivision_line': line,
                     'patterns': patterns
                     })
            elif not all(c in voicing_characters for c in line[::2]):
                # characters with even index must be voicing codes
                error('invalid voicing code')
            else:
                line += ' ' * (subdivisions_per_beat * num_beats - len(line))
                patterns.append(line)
        exercise_dict[exercise_name] = measure_group_list
    return exercise_name_list, exercise_dict


exercises = make_exercises(exercises_text)

if __name__ == '__main__':
    pprint(exercises)
